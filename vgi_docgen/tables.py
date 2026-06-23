"""The buffering ``docgen_merge`` table function for DuckDB via VGI.

``docgen_merge`` is the "many rows -> one document" mail-merge path: it consumes
a *whole* input relation (passed as a ``(SELECT ...)`` subquery, positional
``Arg(0)``), renders the named ``template`` once per row, and concatenates the
results into a SINGLE merged ``.docx`` (a page break between rows), returned as a
one-row, one-column BLOB result set.

    SELECT doc FROM docgen.docgen_merge(
        (SELECT customer, total FROM invoices),
        template := 'invoice.docx');

    -- PDF output (requires headless LibreOffice on PATH)
    SELECT doc FROM docgen.docgen_merge(
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

from dataclasses import dataclass
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
from .schema_utils import field as sfield

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
        examples = [
            FunctionExample(
                sql=(
                    "SELECT doc FROM docgen.docgen_merge("
                    "(SELECT customer, total FROM invoices), template := 'invoice.docx')"
                ),
                description="Merge an invoice per row into one document",
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
