"""Per-row scalar document-generation functions.

``docgen_render`` is a true DuckDB **scalar**: one (template, data) pair per row
in, one rendered document BLOB out -- so it slots into any projection:

    SELECT docgen.main.docgen_render('invoice.docx', {customer: name, total: amt})
    FROM invoices;

    SELECT docgen.main.docgen_render(template_blob, struct_pack(name := name))
    FROM letters;

Polymorphic template input + positional args
--------------------------------------------
VGI / DuckDB *scalar* functions take **positional** arguments only (the
``name := value`` named-arg syntax is a property of table functions, not
scalars). The template reference is therefore accepted as **either**:

- a ``VARCHAR`` path the worker reads (optionally under ``$VGI_DOCGEN_TEMPLATES``), or
- a ``BLOB`` of raw ``.docx`` template bytes passed inline.

These are two distinct DuckDB signatures, so each is its own ``ScalarFunction``
subclass sharing ``Meta.name`` -- the overload idiom the sibling ``vgi-pdf``
worker uses for path-vs-bytes input. The data argument is an arbitrary
``STRUCT`` column (``type_bound = is_struct``), so its shape is resolved at bind
from whatever you pass; every field becomes a Jinja2 variable in the template.

A third boolean positional (``pdf``) opts into LibreOffice PDF conversion; it
defaults to DOCX. PDF without LibreOffice raises a clean error (the merge path)
or yields NULL (here), never a crash.

NULL / hostile semantics: a NULL template or NULL data yields NULL output; a
malformed template, a Jinja render error, or a requested-but-unavailable PDF
conversion also yields NULL -- never a worker crash.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

import pyarrow as pa
from vgi.arguments import ConstParam, Param, Returns
from vgi.metadata import FunctionExample
from vgi.scalar_function import ScalarFunction

from . import core
from .core import DocgenError, TemplateRef
from .meta import object_tags
from .schema_utils import to_context

# Absolute path to the bundled sample DOCX template (shared with tables.py), so
# examples render a real document regardless of the worker's working directory.
from .tables import SAMPLE_TEMPLATE_PATH


def _render_one(ref: TemplateRef | None, ctx_value: Any, want_pdf: bool) -> bytes | None:
    """Render a single row to DOCX (or PDF) bytes, or ``None`` on NULL/failure."""
    if ref is None:
        return None
    try:
        context = to_context(ctx_value)
        docx = core.render_docx(ref, context)
        if want_pdf:
            return core.to_pdf(docx)
        return docx
    except (DocgenError, TypeError, ValueError):
        return None


def _struct_rows(data: Any) -> list[Any]:
    """Decode a struct data argument (a StructArray or AnyArrowValue) to dicts."""
    arr = getattr(data, "value", data)  # AnyArrowValue -> underlying array
    rows: list[Any] = arr.to_pylist()
    return rows


def _render_array(
    refs: list[TemplateRef | None],
    data: Any,
    want_pdf: bool,
) -> pa.Array:
    """Map ``_render_one`` across aligned template/data arrays -> BLOB array."""
    rows = _struct_rows(data)
    out: list[bytes | None] = [_render_one(ref, ctx, want_pdf) for ref, ctx in zip(refs, rows, strict=True)]
    return pa.array(out, type=pa.binary())


# ===========================================================================
# docgen_render(template, data[, pdf]) -> BLOB
#
# Four overloads: path/bytes template x default-docx / explicit-pdf-flag.
# ===========================================================================


_RENDER_CATEGORIES = ["docgen", "template", "blob"]

# Shared per-object discovery/description tags for the docgen_render overloads.
# All four overloads name themselves ``docgen_render`` and describe the SAME
# logical function, so they carry identical title/description/keywords/source.
_RENDER_TITLE = "Render Document from Template"

_RENDER_DESCRIPTION_LLM = (
    "Mail-merge **one DOCX (Microsoft Word) document per input row** from a "
    "template, returning each rendered file as a `BLOB`.\n\n"
    "## What it does\n\n"
    "The first argument is the template, accepted as **either** a `VARCHAR` "
    "path (resolved directly, then under `$VGI_DOCGEN_TEMPLATES`) **or** a "
    "`BLOB` of raw `.docx` bytes. The second argument is an arbitrary `STRUCT` "
    "of row data: every field becomes a Jinja2 variable in the template "
    "(`{{ field }}`), and nested lists/structs drive `{% for %}` loops and "
    "tables. An optional third boolean (`pdf`) converts the result to PDF via a "
    "headless LibreOffice when one is on PATH.\n\n"
    "## When to use it\n\n"
    "Use this scalar to produce a separate filled document for each row -- one "
    "invoice per customer, one letter per recipient, one statement per account. "
    "When you instead want a *single* document concatenating every row, use the "
    "`docgen_merge` table function.\n\n"
    "## Inputs and output\n\n"
    "- `template` -- `VARCHAR` path or `BLOB` `.docx` bytes.\n"
    "- `data` -- `STRUCT`; fields become template variables.\n"
    "- `pdf` (optional) -- `BOOLEAN`; `true` requests PDF output.\n"
    "- Returns a `BLOB`: the rendered `.docx` (or PDF).\n\n"
    "## Edge cases\n\n"
    "Hostile or missing input degrades to `NULL`, never a crash: a `NULL` "
    "template or `NULL` data, a non-DOCX blob, a missing template file, a "
    "malformed template, a Jinja render error, and a requested-but-unavailable "
    "PDF conversion all yield `NULL`."
)

_RENDER_DESCRIPTION_MD = (
    "# Render Document from Template\n\n"
    "Mail-merge **one DOCX document per row** from a template, returning each "
    "rendered file as a `BLOB`.\n\n"
    "## Usage\n\n"
    "Call `docgen_render(template, data)` in any projection: the first argument "
    "is a template file path or inline `.docx` bytes, and the second is a "
    "`STRUCT` of the row's fields (`{customer: name, total: amt}`). Pass a third "
    "`true` argument to request PDF output via headless LibreOffice. Ready-to-run "
    "queries are in this function's example queries.\n\n"
    "## Notes\n\n"
    "- The template is a `VARCHAR` path (resolved under "
    "`$VGI_DOCGEN_TEMPLATES`) or inline `.docx` `BLOB` bytes.\n"
    "- Every field of the `STRUCT` data argument becomes a Jinja2 variable "
    "(`{{ field }}`); nested lists drive `{% for %}` loops.\n"
    "- Missing/hostile input (NULL, non-DOCX blob, bad placeholder, missing "
    "template, unavailable LibreOffice) degrades to `NULL` rather than crashing."
)

_RENDER_KEYWORDS = (
    "docgen, render, mail merge, document generation, docx, word, template, "
    "jinja2, docxtpl, fill template, invoice, letter, statement, contract, "
    "blob, pdf, libreoffice, placeholder"
)

_RENDER_TAGS = {
    **object_tags(
        _RENDER_TITLE,
        _RENDER_DESCRIPTION_LLM,
        _RENDER_DESCRIPTION_MD,
        _RENDER_KEYWORDS,
        "vgi_docgen/scalars.py",
    ),
    # VGI413: name one of the schema's declared vgi.categories.
    "vgi.category": "render",
}

# VGI509 guaranteed-runnable, catalog-qualified examples. Each is self-contained
# and re-runnable against an attached ``docgen`` worker WITHOUT any external
# table: the first renders a real document from the worker's BUNDLED sample
# template (absolute path), and the rest exercise the documented NULL-vs-crash
# discipline. ``expected_result`` is omitted deliberately.
_RENDER_EXECUTABLE_EXAMPLES = json.dumps(
    [
        {
            "description": (
                "Render a document from the bundled sample template filled with a "
                "STRUCT of fields and confirm a non-empty DOCX BLOB is produced."
            ),
            "sql": (
                "SELECT octet_length(docgen.main.docgen_render("
                f"'{SAMPLE_TEMPLATE_PATH}', "
                "{customer: 'Ada Lovelace', total: '99.50'})) > 0 AS ok"
            ),
        },
        {
            "description": "A NULL template passes straight through to a NULL document (NULL-in, NULL-out).",
            "sql": "SELECT docgen.main.docgen_render(NULL::VARCHAR, {customer: 'Ada'}) AS doc",
        },
        {
            "description": "Non-DOCX inline bytes degrade to a clean NULL rather than crashing the worker.",
            "sql": "SELECT docgen.main.docgen_render('not a docx'::BLOB, {x: 1}) AS doc",
        },
    ]
)


class DocgenRenderPath(ScalarFunction):
    """``docgen_render(path, data)`` -- render a template file to a DOCX BLOB."""

    class Meta:
        """VGI metadata for the path-template DOCX render overload."""

        name = "docgen_render"
        categories = _RENDER_CATEGORIES
        description = (
            "Render one DOCX document per row from a template (VARCHAR path, "
            "resolved under $VGI_DOCGEN_TEMPLATES) filled with a STRUCT of row "
            "data; returns the rendered .docx as a BLOB, or NULL on failure."
        )
        tags = {**_RENDER_TAGS, "vgi.executable_examples": _RENDER_EXECUTABLE_EXAMPLES}
        examples = [
            FunctionExample(
                sql=(
                    "SELECT octet_length(docgen.main.docgen_render("
                    f"'{SAMPLE_TEMPLATE_PATH}', "
                    "{customer: 'Ada', total: '99.50'})) > 0 AS ok"
                ),
                description="Render an invoice from the bundled sample template",
            ),
        ]

    @classmethod
    def compute(
        cls,
        template: Annotated[pa.StringArray, Param(doc="Filesystem path to a .docx template.")],
        data: Annotated[
            pa.Array,
            Param(doc="STRUCT of row data; fields become template variables.", type_bound=pa.types.is_struct),
        ],
    ) -> Annotated[pa.BinaryArray, Returns(arrow_type=pa.binary())]:
        """Render each row from its path template to a DOCX BLOB array."""
        refs = [TemplateRef.from_path(p) if p is None else _safe_path(p) for p in template.to_pylist()]
        return _render_array(refs, data, want_pdf=False)


class DocgenRenderPathPdf(ScalarFunction):
    """``docgen_render(path, data, pdf)`` -- render a file, optionally to PDF."""

    class Meta:
        """VGI metadata for the path-template render overload with PDF flag."""

        name = "docgen_render"
        categories = _RENDER_CATEGORIES
        description = (
            "Render one document per row from a template (VARCHAR path) filled "
            "with a STRUCT; with pdf=true convert to PDF via headless "
            "LibreOffice (NULL if LibreOffice is unavailable), else return DOCX."
        )
        tags = dict(_RENDER_TAGS)
        examples = [
            FunctionExample(
                sql="SELECT docgen.main.docgen_render('invoice.docx', {total: '99.50'}, true) AS doc",
                description="Render to PDF (requires LibreOffice on PATH; NULL otherwise)",
            ),
        ]

    @classmethod
    def compute(
        cls,
        template: Annotated[pa.StringArray, Param(doc="Filesystem path to a .docx template.")],
        data: Annotated[
            pa.Array,
            Param(doc="STRUCT of row data; fields become template variables.", type_bound=pa.types.is_struct),
        ],
        pdf: Annotated[bool, ConstParam("Convert to PDF via LibreOffice (default DOCX).", arrow_type=pa.bool_())],
    ) -> Annotated[pa.BinaryArray, Returns(arrow_type=pa.binary())]:
        """Render each row from its path template, optionally to PDF, as a BLOB array."""
        refs = [None if p is None else _safe_path(p) for p in template.to_pylist()]
        return _render_array(refs, data, want_pdf=bool(pdf))


class DocgenRenderBytes(ScalarFunction):
    """``docgen_render(blob, data)`` -- render inline template bytes to a DOCX."""

    class Meta:
        """VGI metadata for the inline-bytes DOCX render overload."""

        name = "docgen_render"
        categories = _RENDER_CATEGORIES
        description = (
            "Render one DOCX document per row from inline template bytes (BLOB) "
            "filled with a STRUCT of row data; returns the rendered .docx as a "
            "BLOB, or NULL on failure."
        )
        tags = dict(_RENDER_TAGS)
        examples = [
            FunctionExample(
                sql="SELECT docgen.main.docgen_render('not a docx'::BLOB, {customer: 'Ada'}) AS doc",
                description="Render from inline template BLOB bytes (non-DOCX bytes yield a clean NULL)",
            ),
        ]

    @classmethod
    def compute(
        cls,
        template: Annotated[pa.BinaryArray, Param(doc="Raw .docx template bytes.", arrow_type=pa.binary())],
        data: Annotated[
            pa.Array,
            Param(doc="STRUCT of row data; fields become template variables.", type_bound=pa.types.is_struct),
        ],
    ) -> Annotated[pa.BinaryArray, Returns(arrow_type=pa.binary())]:
        """Render each row from inline template bytes to a DOCX BLOB array."""
        refs = [None if b is None else _safe_bytes(b) for b in template.to_pylist()]
        return _render_array(refs, data, want_pdf=False)


class DocgenRenderBytesPdf(ScalarFunction):
    """``docgen_render(blob, data, pdf)`` -- render template bytes, optional PDF."""

    class Meta:
        """VGI metadata for the inline-bytes render overload with PDF flag."""

        name = "docgen_render"
        categories = _RENDER_CATEGORIES
        description = (
            "Render one document per row from inline template bytes (BLOB) "
            "filled with a STRUCT; with pdf=true convert to PDF via headless "
            "LibreOffice (NULL if unavailable), else return DOCX."
        )
        tags = dict(_RENDER_TAGS)
        examples = [
            FunctionExample(
                sql="SELECT docgen.main.docgen_render('not a docx'::BLOB, {total: '99.50'}, true) AS doc",
                description="Render template bytes to PDF (requires LibreOffice; NULL otherwise)",
            ),
        ]

    @classmethod
    def compute(
        cls,
        template: Annotated[pa.BinaryArray, Param(doc="Raw .docx template bytes.", arrow_type=pa.binary())],
        data: Annotated[
            pa.Array,
            Param(doc="STRUCT of row data; fields become template variables.", type_bound=pa.types.is_struct),
        ],
        pdf: Annotated[bool, ConstParam("Convert to PDF via LibreOffice (default DOCX).", arrow_type=pa.bool_())],
    ) -> Annotated[pa.BinaryArray, Returns(arrow_type=pa.binary())]:
        """Render each row from inline template bytes, optionally to PDF, as a BLOB array."""
        refs = [None if b is None else _safe_bytes(b) for b in template.to_pylist()]
        return _render_array(refs, data, want_pdf=bool(pdf))


def _safe_path(ref: str) -> TemplateRef | None:
    """Resolve a path ref, returning ``None`` (=> NULL output) on any failure."""
    try:
        return TemplateRef.from_path(ref)
    except DocgenError:
        return None


def _safe_bytes(ref: bytes) -> TemplateRef | None:
    """Wrap inline bytes, returning ``None`` (=> NULL output) on bad bytes."""
    try:
        return TemplateRef.from_bytes(ref)
    except DocgenError:
        return None


SCALAR_FUNCTIONS: list[type] = [
    DocgenRenderPath,
    DocgenRenderPathPdf,
    DocgenRenderBytes,
    DocgenRenderBytesPdf,
]
