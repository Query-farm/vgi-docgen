"""VGI worker exposing DOCX mail-merge / document generation to DuckDB/SQL.

The inverse of vgi-tika / vgi-pdf: instead of pulling text/structure *out* of
documents, this merges query data *into* DOCX templates to produce filled
documents (invoices, contracts, statements, letters), returning each rendered
file as a BLOB. Assembles the scalar (one doc per row) and buffering (many rows
-> one merged doc) functions into a single ``docgen`` catalog over stdio.

    ATTACH 'docgen' (TYPE vgi, LOCATION 'uv run docgen_worker.py');
    SELECT docgen.docgen_render('invoice.docx', {total: amt}) FROM inv;
    SELECT doc FROM docgen.docgen_merge((SELECT * FROM inv), template := 'invoice.docx');
"""

from __future__ import annotations

import json
import sys

from vgi import Worker
from vgi.catalog import Catalog, Schema

from vgi_docgen.discovery import SAMPLE_TEMPLATES_TABLE
from vgi_docgen.meta import keywords_json
from vgi_docgen.scalars import SCALAR_FUNCTIONS
from vgi_docgen.tables import SAMPLE_TEMPLATE_PATH, TABLE_FUNCTIONS

_FUNCTIONS: list[type] = [*SCALAR_FUNCTIONS, *TABLE_FUNCTIONS]

_CATALOG_DESCRIPTION_LLM = (
    "Mail-merge SQL query data into DOCX (Microsoft Word) templates to produce "
    "filled documents -- invoices, contracts, statements, letters -- returned as "
    "BLOBs for DuckDB. The inverse of text-extraction workers: it pushes row data "
    "INTO templates rather than pulling text out. Use the scalar docgen_render for "
    "one document per row (template path or inline bytes, plus a STRUCT of fields "
    "that become Jinja2 variables), and the table function docgen_merge to "
    "concatenate one render per input row into a single merged document. Output is "
    "DOCX by default, or PDF (pdf:=true) via headless LibreOffice when available."
)

_CATALOG_DESCRIPTION_MD = (
    "# docgen: DOCX Mail Merge and Document Generation in SQL\n\n"
    "**Turn DuckDB query results into finished Word documents and PDFs — generate "
    "invoices, contracts, statements, and letters straight from SQL with mail-merge "
    "templates, no application code required.**\n\n"
    "`docgen` is a VGI worker that does the inverse of text-extraction tools such as "
    "vgi-tika and vgi-pdf: rather than pulling text and structure *out* of documents, "
    "it pushes your SQL row data *into* DOCX (Microsoft Word) templates to produce "
    "filled, ready-to-send documents. Each rendered document is returned to DuckDB as a "
    "BLOB, so you can write it to a file, store it in a table, or stream it onward. It "
    "is built for anyone who needs to automate document production at query time — "
    "billing and finance teams generating invoices and account statements, operations "
    "teams producing contracts and form letters, and developers building reporting or "
    "notification pipelines directly on their data warehouse.\n\n"
    "Rendering is powered by [docxtpl](https://github.com/elapouya/python-docx-template) "
    "([documentation](https://docxtpl.readthedocs.io/)), which layers the "
    "[Jinja2](https://jinja.palletsprojects.com/) templating engine over "
    "[python-docx](https://github.com/python-openxml/python-docx) "
    "([documentation](https://python-docx.readthedocs.io/)). You design a normal `.docx` "
    "template in Word using `{{ field }}` placeholders and `{% for %}` loops, and every "
    "field or column from your query becomes a template variable. Multi-document output "
    "is stitched together with [docxcompose](https://pypi.org/project/docxcompose/), and "
    "optional DOCX-to-PDF conversion is handled by a headless "
    "[LibreOffice](https://www.libreoffice.org/) when it is available on the host (PDF is "
    "always optional and never a hard dependency).\n\n"
    "The catalog exposes two functions. The scalar `docgen_render(template, data[, pdf])` "
    "renders one document per row: pass a template — either a VARCHAR path (resolved "
    "directly, then under `$VGI_DOCGEN_TEMPLATES`) or inline `.docx` BLOB bytes — and a "
    "`STRUCT` of fields that become the Jinja2 variables, with an optional `pdf` flag. "
    "The table function "
    "`docgen_merge(relation, template := ..., [pdf := true])` consumes an entire "
    "relation and concatenates one render per input row into a single combined document, "
    "ideal for batch statement runs or multi-page contract packs.\n\n"
    "The `sample_templates` discovery table lists every template the worker ships "
    "along with its absolute path and the placeholder fields it expects, so an "
    "agent can produce a real document without supplying a file of its own. See "
    "the catalog's example queries for ready-to-run usage of each function.\n\n"
    "Untrusted bytes are magic-checked before rendering, "
    "and bad input degrades cleanly to NULL (scalar) or a visible error (merge)."
)

_SCHEMA_DESCRIPTION_LLM = (
    "DOCX mail-merge / document-generation functions: render a Word template "
    "filled with per-row STRUCT data into a document BLOB (docgen_render), or "
    "merge one render per input row into a single combined document "
    "(docgen_merge). DOCX by default, PDF on request."
)

_SCHEMA_DESCRIPTION_MD = (
    "## DOCX mail merge in SQL\n\n"
    "Turn query results into finished Word documents. This schema mail-merges "
    "row data into `.docx` templates and returns each rendered file as a `BLOB`, "
    "so documents are produced at query time with no application code.\n\n"
    "### Key concepts\n\n"
    "- **Templates** are ordinary Word files with `{{ field }}` placeholders and "
    "`{% for %}` loops, powered by Jinja2 over python-docx.\n"
    "- **Data** comes straight from your columns: every field or column becomes a "
    "template variable at render time.\n"
    "- **Output** is a document `BLOB` — DOCX by default, or PDF when a headless "
    "LibreOffice is available on the host.\n\n"
    "### When to use it\n\n"
    "Reach for this schema to automate document production — invoices, account "
    "statements, contracts, and form letters — either one filled document per row "
    "or a whole relation merged into a single combined document. Untrusted input "
    "is magic-checked and degrades cleanly rather than crashing the worker.\n"
)

_SCHEMA_KEYWORDS = (
    "docgen, document generation, mail merge, docx, word, template, render, "
    "merge, docgen_render, docgen_merge, jinja2, blob, pdf, invoice, letter"
)

# VGI413 category registry for the schema. Each function tags itself with a
# `vgi.category` naming one of these; categories drive the worker's navigation,
# listing sections, and SEO descriptions.
_SCHEMA_CATEGORIES = json.dumps(
    [
        {
            "name": "render",
            "description": "Per-row rendering: produce one filled document for each input row.",
        },
        {
            "name": "merge",
            "description": "Whole-relation merge: combine every input row into one merged document.",
        },
    ]
)

# VGI152 fixed analyst-task suite (`vgi.agent_test_tasks`) so `vgi-lint simulate`
# can measure how well an agent actually drives this worker. Each reference_sql
# is deterministic and self-contained: it collapses non-deterministic document
# BYTES to a stable boolean/count, so grading is reproducible. `ignore_column_names`
# lets the analyst pick any output column name; results are single-row so order is
# irrelevant. The sample template path is given IN the prompt so the analyst can
# reproduce the happy-path render without guessing a machine-specific path.
_AGENT_TEST_TASKS = json.dumps(
    [
        {
            "name": "render_from_sample_template",
            "prompt": (
                "The docgen worker ships a sample invoice template at the absolute path "
                f"'{SAMPLE_TEMPLATE_PATH}'. Using it, render one Word document for customer "
                "'Ada Lovelace' with total '99.50', and return a single boolean column "
                "reporting whether a non-empty document BLOB was produced."
            ),
            "reference_sql": (
                "SELECT octet_length(docgen.main.docgen_render("
                f"'{SAMPLE_TEMPLATE_PATH}', "
                "{customer: 'Ada Lovelace', total: '99.50'})) > 0 AS document_produced"
            ),
            "ignore_column_names": True,
        },
        {
            "name": "null_template_is_null",
            "prompt": (
                "Demonstrate the docgen worker's NULL-safety: when the template argument to "
                "docgen_render is a NULL VARCHAR, the rendered document must be NULL. Return a "
                "single boolean column that is true when the output is NULL."
            ),
            "reference_sql": ("SELECT docgen.main.docgen_render(NULL::VARCHAR, {customer: 'Ada'}) IS NULL AS is_null"),
            "ignore_column_names": True,
        },
        {
            "name": "empty_merge_yields_no_rows",
            "prompt": (
                "Using docgen_merge, show that merging an empty input relation (no rows) "
                "produces no output document rows. Return the number of output rows as a "
                "single column."
            ),
            "reference_sql": (
                "SELECT count(*) AS n FROM docgen.main.docgen_merge("
                "(SELECT 'Ada' AS customer WHERE false), template := 'invoice.docx')"
            ),
            "ignore_column_names": True,
        },
        {
            "name": "discover_sample_templates",
            "prompt": (
                "The docgen worker ships one or more ready-to-use document templates. Without "
                "being told the path, discover how many templates it bundles. Return the count "
                "as a single column."
            ),
            "reference_sql": ("SELECT count(*) AS n FROM docgen.main.sample_templates"),
            "ignore_column_names": True,
        },
        {
            "name": "sample_template_fields",
            "prompt": (
                "Using only the docgen worker's own catalog, find the placeholder fields the "
                "bundled 'sample_invoice' template expects. Return a single boolean column that "
                "is true when its fields are exactly 'customer' and 'total'."
            ),
            "reference_sql": (
                "SELECT fields = 'customer, total' AS ok "
                "FROM docgen.main.sample_templates WHERE name = 'sample_invoice'"
            ),
            "ignore_column_names": True,
        },
    ]
)

# VGI506 representative example queries for the schema. Catalog-qualified and
# self-contained: an unresolved template path renders to a clean NULL, and an
# empty merge relation yields zero rows -- so each query runs without error.
_SCHEMA_EXAMPLE_QUERIES = (
    "SELECT docgen.main.docgen_render('invoice.docx', {customer: 'Ada', total: '99.50'}) AS doc;\n"
    "SELECT docgen.main.docgen_render('not a docx'::BLOB, {customer: 'Ada'}) AS doc;\n"
    "SELECT docgen.main.docgen_render('invoice.docx', {total: '99.50'}, true) AS doc;\n"
    "SELECT doc FROM docgen.main.docgen_merge((SELECT 'Ada' AS customer WHERE false), "
    "template := 'invoice.docx');"
)

_DOCGEN_CATALOG = Catalog(
    name="docgen",
    default_schema="main",
    comment="Mail-merge SQL data into DOCX templates -> filled documents (DOCX/PDF) as BLOBs.",
    source_url="https://github.com/Query-farm/vgi-docgen",
    tags={
        "vgi.title": "Document Generation (DOCX Mail Merge)",
        "vgi.keywords": keywords_json(
            "docgen, document generation, mail merge, docx, word, template, "
            "jinja2, docxtpl, docxcompose, render, merge, invoice, letter, "
            "statement, contract, blob, pdf, libreoffice"
        ),
        "vgi.doc_llm": _CATALOG_DESCRIPTION_LLM,
        "vgi.doc_md": _CATALOG_DESCRIPTION_MD,
        "vgi.author": "Query.Farm",
        "vgi.copyright": "Copyright 2026 Query Farm LLC - https://query.farm",
        "vgi.license": "MIT",
        "vgi.support_contact": "https://github.com/Query-farm/vgi-docgen/issues",
        "vgi.support_policy_url": "https://github.com/Query-farm/vgi-docgen/blob/main/README.md",
        "vgi.agent_test_tasks": _AGENT_TEST_TASKS,
    },
    schemas=[
        Schema(
            name="main",
            comment="Merge SQL data into DOCX templates -> filled documents (DOCX/PDF) as BLOBs",
            tags={
                "vgi.title": "Document Generation — main",
                "vgi.keywords": keywords_json(_SCHEMA_KEYWORDS),
                # VGI123 classifying tags use BARE keys (NOT vgi.-namespaced).
                "domain": "documents",
                "category": "document-generation",
                "topic": "docx-mail-merge",
                # source_url is set only on the catalog object (VGI139).
                "vgi.categories": _SCHEMA_CATEGORIES,
                "vgi.example_queries": _SCHEMA_EXAMPLE_QUERIES,
                "vgi.doc_llm": _SCHEMA_DESCRIPTION_LLM,
                "vgi.doc_md": _SCHEMA_DESCRIPTION_MD,
            },
            functions=list(_FUNCTIONS),
            tables=[SAMPLE_TEMPLATES_TABLE],
        ),
    ],
)


class DocgenWorker(Worker):
    """Worker process hosting the ``docgen`` catalog."""

    catalog = _DOCGEN_CATALOG


def main() -> None:
    """Run the worker (stdio by default; pass ``--http`` for the HTTP server)."""
    DocgenWorker.main()


def main_http() -> None:
    """Run the worker over HTTP (injects ``--http`` into the worker CLI)."""
    argv = sys.argv[1:]
    if "--http" not in argv:
        argv = ["--http", *argv]
    sys.argv = [sys.argv[0], *argv]
    DocgenWorker.main()
