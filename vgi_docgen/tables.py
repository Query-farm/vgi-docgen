"""The buffering ``docgen_merge`` table function for DuckDB via VGI.

``docgen_merge`` is the "many rows -> one document" mail-merge path: it consumes
a *whole* input relation (passed as a ``(SELECT ...)`` subquery, positional
``Arg(0)``), renders the named ``template`` once per row, and concatenates the
results into a SINGLE merged ``.docx`` (a page break between rows), returned as a
one-row, one-column BLOB result set.

    SELECT doc FROM docgen.main.docgen_merge(
        (SELECT customer, total FROM invoices),
        template := 'invoice.docx');

    -- PDF output (requires headless LibreOffice on PATH)
    SELECT doc FROM docgen.main.docgen_merge(
        (SELECT customer FROM letters),
        template := 'letter.docx', pdf := true);

Because the merge needs every row before any output, this is a
``TableBufferingFunction`` (Sink+Source): it sinks all input batches, then
renders+merges once in finalize. The template is a NAMED string arg (table
functions support ``name := value``; scalars do not) -- a ``VARCHAR`` path
resolved under ``$VGI_DOCGEN_TEMPLATES``. Every column of the relation is
available to the template as a Jinja2 variable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, ClassVar

import pyarrow as pa
from vgi.arguments import Arg, TableInput
from vgi.invocation import BindResponse
from vgi.metadata import FunctionExample
from vgi.table_buffering_function import TableBufferingParams
from vgi.table_function import BindParams
from vgi_rpc import OutputCollector

from . import core
from .buffering import DrainState, SinkBuffer
from .core import DocgenError, TemplateRef
from .meta import object_tags
from .schema_utils import field as sfield

_MERGE_TITLE = "Merge Rows into One Document"

_MERGE_DESCRIPTION_LLM = (
    "Mail-merge a **whole input relation into a SINGLE merged DOCX (or PDF) "
    "document**, returned as a one-row, one-column `BLOB`.\n\n"
    "## What it does\n\n"
    '`docgen_merge` is the "many rows -> one document" path. It consumes an '
    "entire input relation (passed positionally as a `(SELECT ...)` subquery), "
    "renders the named `template` once per row, and concatenates the results "
    "into one `.docx`, with a page break between rows. Every column of the "
    "relation is exposed to the template as a Jinja2 variable (`{{ column }}`). "
    "Because it is a buffering (Sink+Source) function, it sinks every input "
    "batch first and renders+merges once at finalize.\n\n"
    "## When to use it\n\n"
    "Use it to assemble one combined document from many rows -- a single PDF of "
    "all monthly statements, one Word file containing every contract. When you "
    "instead want a *separate* document per row, use the `docgen_render` scalar.\n\n"
    "## Inputs and output\n\n"
    "- `data` -- the input relation, a positional `(SELECT ...)` subquery; "
    "every column becomes a template variable.\n"
    "- `template` -- named `VARCHAR` arg: path to a `.docx` template, resolved "
    "under `$VGI_DOCGEN_TEMPLATES`.\n"
    "- `pdf` -- named `BOOLEAN` arg; `true` converts the merged document to PDF "
    "via headless LibreOffice.\n"
    "- Returns a single `doc` `BLOB` row.\n\n"
    "## Edge cases\n\n"
    "An **empty input relation yields zero output rows** (no document). A "
    "missing/typo'd template name or an unavailable LibreOffice surfaces as a "
    "clean DuckDB error (the merge path fails loudly rather than emitting a "
    "silently empty file); the worker stays alive and serving afterwards."
)

_MERGE_DESCRIPTION_MD = (
    "# Merge Rows into One Document\n\n"
    "Mail-merge a whole relation into a **single merged DOCX/PDF** `BLOB` -- "
    "one template render per input row, concatenated with a page break.\n\n"
    "## Usage\n\n"
    "Pass the input relation as the positional `(...)` subquery argument and the "
    "template as the named `template := '...'` argument; add `pdf := true` to "
    "convert the merged result via headless LibreOffice. The single `doc` column "
    "carries the combined document. Ready-to-run queries are in this function's "
    "example queries.\n\n"
    "## Notes\n\n"
    "- The relation is the positional `(...)` subquery argument; every column is "
    "a Jinja2 template variable.\n"
    "- `template` and `pdf` are named args (`name := value`), supported by "
    "table functions.\n"
    "- An empty input relation produces zero output rows; a missing template "
    "raises a clean DuckDB error."
)

_MERGE_KEYWORDS = (
    "docgen, merge, mail merge, document generation, concatenate, combine, "
    "docx, word, template, jinja2, docxtpl, docxcompose, single document, "
    "batch, blob, pdf, libreoffice, statements, contracts"
)

# Absolute path to the bundled sample DOCX template, resolved at import time so
# examples resolve regardless of the worker's working directory.
SAMPLE_TEMPLATE_PATH = str(Path(__file__).resolve().parent / "data" / "sample_invoice.docx")

# VGI509 guaranteed-runnable, catalog-qualified examples. They merge real rows
# against the worker's BUNDLED sample template (resolved by absolute path), so
# the example produces an actual non-empty merged document -- self-contained and
# re-runnable with no external table or user-supplied file. ``expected_result``
# is omitted deliberately.
_MERGE_EXECUTABLE_EXAMPLES = json.dumps(
    [
        {
            "description": (
                "Merge two rows against the worker's bundled sample template into "
                "ONE document and confirm a non-empty DOCX BLOB is produced."
            ),
            "sql": (
                "SELECT octet_length(doc) > 0 AS ok FROM docgen.main.docgen_merge("
                "(SELECT * FROM (VALUES ('Ada', '99.50'), ('Grace', '42.00')) "
                f"AS t(customer, total)), template := '{SAMPLE_TEMPLATE_PATH}')"
            ),
        }
    ]
)

_MERGE_SCHEMA = pa.schema(
    [
        sfield(
            "doc",
            pa.binary(),
            "The single merged document (DOCX, or PDF when pdf:=true) as a BLOB.",
            nullable=False,
        ),
    ]
)


@dataclass(slots=True, frozen=True)
class MergeArgs:
    """Bound arguments for ``docgen_merge``.

    Attributes:
        data: The input relation; every column is exposed as a template variable.
        template: Path to a ``.docx`` template, resolved under ``$VGI_DOCGEN_TEMPLATES``.
        pdf: Convert the merged document to PDF via headless LibreOffice.
    """

    data: Annotated[TableInput, Arg(0, doc="Relation; every column is a template variable.")]
    template: Annotated[
        str,
        Arg("template", default="", doc="Path to a .docx template (under $VGI_DOCGEN_TEMPLATES)."),
    ]
    pdf: Annotated[
        bool,
        Arg("pdf", default=False, doc="Convert the merged document to PDF via LibreOffice."),
    ]


class DocgenMerge(SinkBuffer[MergeArgs, DrainState]):
    """Mail-merge: one template + many rows -> one merged document BLOB."""

    FunctionArguments: ClassVar[type] = MergeArgs

    class Meta:
        """VGI metadata for the ``docgen_merge`` buffering table function."""

        name = "docgen_merge"
        description = (
            "Mail-merge: render a DOCX 'template' once per input row and "
            "concatenate into ONE merged document (page break between rows), "
            "returned as a single BLOB. With pdf:=true, convert via headless "
            "LibreOffice. Every relation column is a template variable."
        )
        categories = ["docgen", "template", "merge", "blob"]
        tags = {
            **object_tags(
                _MERGE_TITLE,
                _MERGE_DESCRIPTION_LLM,
                _MERGE_DESCRIPTION_MD,
                _MERGE_KEYWORDS,
                "vgi_docgen/tables.py",
            ),
            # VGI413: name one of the schema's declared vgi.categories.
            "vgi.category": "merge",
            "vgi.executable_examples": _MERGE_EXECUTABLE_EXAMPLES,
            # VGI307/VGI321/VGI414: structured static result schema (migrated from
            # the retired free-form vgi.result_columns_md).
            "vgi.result_columns_schema": json.dumps(
                [
                    {
                        "name": "doc",
                        "type": "BLOB",
                        "description": (
                            "The single merged document -- DOCX by default, or PDF when pdf:=true -- "
                            "containing one template render per input row, separated by a page break."
                        ),
                    }
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql=(
                    "SELECT octet_length(doc) > 0 AS ok FROM docgen.main.docgen_merge("
                    "(SELECT * FROM (VALUES ('Ada', '99.50'), ('Grace', '42.00')) "
                    f"AS t(customer, total)), template := '{SAMPLE_TEMPLATE_PATH}')"
                ),
                description="Merge two rows into one document using the bundled sample template",
            )
        ]

    @classmethod
    def on_bind(cls, params: BindParams[MergeArgs]) -> BindResponse:
        """Declare the single-column BLOB output schema at bind time."""
        return BindResponse(output_schema=_MERGE_SCHEMA)

    @classmethod
    def initial_finalize_state(cls, finalize_state_id: bytes, params: TableBufferingParams[MergeArgs]) -> DrainState:
        """Start each finalize stream undrained, so it emits exactly one document."""
        return DrainState()

    @classmethod
    def finalize(
        cls,
        params: TableBufferingParams[MergeArgs],
        finalize_state_id: bytes,
        state: DrainState,
        out: OutputCollector,
    ) -> None:
        """Render the template against every buffered row and emit one merged BLOB."""
        if state.done:
            out.finish()
            return
        state.done = True

        args = params.args
        if not args.template:
            raise DocgenError("docgen_merge requires a 'template' argument (a .docx path)")

        ref = TemplateRef.from_path(args.template)
        assert ref is not None  # non-empty template => never None
        contexts = cls.buffered_contexts(params)
        merged = core.merge_docx(ref, contexts)
        if args.pdf:
            merged = core.to_pdf(merged)

        batch = pa.RecordBatch.from_pydict(
            {"doc": pa.array([merged], type=pa.binary())},
            schema=params.output_schema,
        )
        out.emit(batch)


TABLE_FUNCTIONS: list[type] = [DocgenMerge]
