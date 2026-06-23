"""Per-row scalar document-generation functions.

``docgen_render`` is a true DuckDB **scalar**: one (template, data) pair per row
in, one rendered document BLOB out -- so it slots into any projection:

    SELECT docgen.docgen_render('invoice.docx', {customer: name, total: amt})
    FROM invoices;

    SELECT docgen.docgen_render(template_blob, struct_pack(name := name))
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

from typing import Annotated, Any

import pyarrow as pa
from vgi.arguments import ConstParam, Param, Returns
from vgi.metadata import FunctionExample
from vgi.scalar_function import ScalarFunction

from . import core
from .core import DocgenError, TemplateRef
from .schema_utils import to_context


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
        examples = [
            FunctionExample(
                sql="SELECT docgen.docgen_render('invoice.docx', {customer: name, total: amt}) FROM inv",
                description="Render an invoice per row from a template file",
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
        examples = [
            FunctionExample(
                sql="SELECT docgen.docgen_render('invoice.docx', {total: amt}, true) FROM inv",
                description="Render to PDF (requires LibreOffice on PATH)",
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
        examples = [
            FunctionExample(
                sql="SELECT docgen.docgen_render(tpl, {customer: name}) FROM letters, templates",
                description="Render from a template held as bytes",
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
        examples = [
            FunctionExample(
                sql="SELECT docgen.docgen_render(tpl, {total: amt}, true) FROM inv, templates",
                description="Render template bytes to PDF (requires LibreOffice)",
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
