"""The ``sample_templates`` browsable discovery table for the docgen worker.

``docgen`` ships a ready-to-use sample ``.docx`` template so an agent can render
a real document without supplying its own file first. That template lives at a
machine-specific absolute path, and its ``{{ placeholder }}`` fields are the
exact keys the ``STRUCT`` data argument must carry. Both are things an agent
would otherwise have to *guess*.

``sample_templates`` exposes them as a plain, argument-free, browsable table
(``SELECT * FROM docgen.main.sample_templates``): one row per bundled template,
carrying its logical ``name``, absolute ``path``, the number of placeholder
``fields`` it expects, the ``fields`` themselves (comma-separated), and a human
``description``. The field list is derived from the template bytes at scan time
(docxtpl's undeclared-variable analysis), so the registry can never drift from
the document's real placeholders.

    SELECT name, path, fields FROM docgen.main.sample_templates;
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar

import pyarrow as pa
from vgi.catalog import Table
from vgi.metadata import FunctionExample
from vgi.table_function import (
    BindParams,
    ProcessParams,
    TableCardinality,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from . import core
from .meta import keywords_json, object_tags
from .schema_utils import field
from .tables import SAMPLE_TEMPLATE_PATH

_DISCOVERY_PATH = "vgi_docgen/discovery.py"


@dataclass(kw_only=True)
class _NoArgs:
    """Marker: the discovery table takes no arguments."""


# The bundled template registry: (logical name, absolute path, description).
# Adding another shipped template is a one-line append here; its placeholder
# fields are read from the file at scan time, never hand-maintained.
_BUNDLED_TEMPLATES: list[tuple[str, str, str]] = [
    (
        "sample_invoice",
        SAMPLE_TEMPLATE_PATH,
        "A minimal single-page invoice template with a customer header and a total; "
        "the worker's canonical example template.",
    ),
]

_SAMPLE_TEMPLATES_SCHEMA = pa.schema(
    [
        field("name", pa.string(), "Logical template name.", nullable=False),
        field("path", pa.string(), "Absolute filesystem path to the .docx template.", nullable=False),
        field("field_count", pa.int32(), "Number of Jinja2 template variables the template expects.", nullable=False),
        field(
            "fields",
            pa.string(),
            "Comma-separated Jinja2 template variable names (the keys the STRUCT data must carry).",
            nullable=False,
        ),
        field("description", pa.string(), "What the template is for.", nullable=False),
    ]
)

_SAMPLE_TEMPLATES_RESULT_COLUMNS = json.dumps(
    [
        {"name": "name", "type": "VARCHAR", "description": "Logical template name."},
        {"name": "path", "type": "VARCHAR", "description": "Absolute filesystem path to the .docx template."},
        {
            "name": "field_count",
            "type": "INTEGER",
            "description": "Number of Jinja2 template variables the template expects.",
        },
        {
            "name": "fields",
            "type": "VARCHAR",
            "description": "Comma-separated Jinja2 template variable names (the keys the STRUCT data must carry).",
        },
        {"name": "description", "type": "VARCHAR", "description": "What the template is for."},
    ]
)

_SAMPLE_TEMPLATES_DOC_LLM = (
    "## `sample_templates`\n\n"
    "A **browsable table** (no arguments) listing the DOCX templates the worker "
    "ships, so an agent can render a real document without supplying a file. One "
    "row per bundled template:\n\n"
    "- `name` (`VARCHAR`) -- logical template name, e.g. `sample_invoice`.\n"
    "- `path` (`VARCHAR`) -- the absolute filesystem path to pass as the "
    "`template` argument of `docgen_render` / `docgen_merge`.\n"
    "- `field_count` (`INTEGER`) -- how many placeholder fields the template has.\n"
    "- `fields` (`VARCHAR`) -- the comma-separated `{{ placeholder }}` names; "
    "these are exactly the keys the `STRUCT` data argument must provide.\n"
    "- `description` (`VARCHAR`) -- what the template is for.\n\n"
    "Read `path` and `fields` from this table, then call "
    "`docgen_render(path, {field: value, ...})` to produce a document."
)

_SAMPLE_TEMPLATES_DOC_MD = (
    "# `sample_templates`\n\n"
    "Registry of the DOCX templates bundled with the worker, so you can render a "
    "real document out of the box.\n\n"
    "## Columns\n\n"
    "- `name` (`VARCHAR`) -- logical template name.\n"
    "- `path` (`VARCHAR`) -- absolute path to pass as the `template` argument.\n"
    "- `field_count` (`INTEGER`) -- number of placeholder fields.\n"
    "- `fields` (`VARCHAR`) -- comma-separated placeholder names to supply as data.\n"
    "- `description` (`VARCHAR`) -- what the template is for.\n\n"
    "Look up a template's `path` and `fields` here, then feed them to "
    "`docgen_render` or `docgen_merge`."
)

_SAMPLE_TEMPLATES_KEYWORDS = (
    "sample templates, template registry, discovery, docx, placeholders, fields, "
    "template path, sample_invoice, invoice template, browse templates"
)

_SAMPLE_TEMPLATES_EXAMPLE_QUERIES = json.dumps(
    [
        {
            "description": "List every bundled template with its path and the placeholder fields it expects.",
            "sql": "SELECT name, path, fields FROM docgen.main.sample_templates ORDER BY name",
        },
        {
            "description": "Count how many document templates the worker ships out of the box.",
            "sql": "SELECT count(*) AS template_count FROM docgen.main.sample_templates",
        },
    ]
)


@init_single_worker
@bind_fixed_schema
class SampleTemplatesFunction(TableFunctionGenerator[_NoArgs]):
    """Backing generator for the ``sample_templates`` discovery table."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = _SAMPLE_TEMPLATES_SCHEMA

    class Meta:
        """VGI metadata for the sample-templates discovery table."""

        name = "sample_templates"
        description = "The DOCX templates the worker ships, with their path and template variables (discovery table)"
        categories = ["docgen", "template", "discovery"]
        tags = {
            **object_tags(
                "Bundled Document Templates",
                _SAMPLE_TEMPLATES_DOC_LLM,
                _SAMPLE_TEMPLATES_DOC_MD,
                _SAMPLE_TEMPLATES_KEYWORDS,
                _DISCOVERY_PATH,
            ),
            "vgi.category": "render",
            "vgi.result_columns_schema": _SAMPLE_TEMPLATES_RESULT_COLUMNS,
            "vgi.example_queries": _SAMPLE_TEMPLATES_EXAMPLE_QUERIES,
        }
        examples = [
            FunctionExample(
                sql="SELECT name, path, fields FROM docgen.main.sample_templates ORDER BY name",
                description="List the bundled templates with their placeholder fields",
            ),
        ]

    @classmethod
    def cardinality(cls, params: BindParams[_NoArgs]) -> TableCardinality:
        """Estimated and maximum row count for the planner."""
        return TableCardinality(estimate=len(_BUNDLED_TEMPLATES), max=len(_BUNDLED_TEMPLATES))

    @classmethod
    def process(cls, params: ProcessParams[_NoArgs], state: None, out: OutputCollector) -> None:
        """Emit one row per bundled template, deriving its fields from the file."""
        names: list[str] = []
        paths: list[str] = []
        counts: list[int] = []
        field_lists: list[str] = []
        descriptions: list[str] = []
        for name, path, description in _BUNDLED_TEMPLATES:
            ref = core.TemplateRef.from_path(path)
            fields = core.template_fields(ref) if ref is not None else []
            names.append(name)
            paths.append(path)
            counts.append(len(fields))
            field_lists.append(", ".join(fields))
            descriptions.append(description)
        out.emit(
            pa.RecordBatch.from_pydict(
                {
                    "name": names,
                    "path": paths,
                    "field_count": counts,
                    "fields": field_lists,
                    "description": descriptions,
                },
                schema=params.output_schema,
            )
        )
        out.finish()


# The browsable discovery table (VGI146): a real table backed by the generator
# above, so an agent can `SELECT * FROM docgen.main.sample_templates` and read
# each bundled template's path + placeholder fields before rendering.
SAMPLE_TEMPLATES_TABLE = Table(
    name="sample_templates",
    function=SampleTemplatesFunction,
    comment="The DOCX templates the worker ships, with their path and template variables (discovery table).",
    primary_key=(("name",),),
    not_null=("name", "path", "field_count", "fields", "description"),
    column_comments={
        "name": "Logical template name.",
        "path": "Absolute filesystem path to the .docx template (pass as the `template` argument).",
        "field_count": "Number of Jinja2 template variables the template expects.",
        "fields": "Comma-separated Jinja2 template variable names (the keys the STRUCT data must carry).",
        "description": "What the template is for.",
    },
    tags={
        "vgi.title": "Bundled Document Templates",
        "vgi.doc_llm": _SAMPLE_TEMPLATES_DOC_LLM,
        "vgi.doc_md": _SAMPLE_TEMPLATES_DOC_MD,
        "vgi.keywords": keywords_json(_SAMPLE_TEMPLATES_KEYWORDS),
        "vgi.category": "render",
        "domain": "documents",
        "vgi.example_queries": _SAMPLE_TEMPLATES_EXAMPLE_QUERIES,
    },
)
