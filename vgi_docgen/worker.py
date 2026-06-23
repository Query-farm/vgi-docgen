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

import sys

from vgi import Worker
from vgi.catalog import Catalog, Schema

from vgi_docgen.scalars import SCALAR_FUNCTIONS
from vgi_docgen.tables import TABLE_FUNCTIONS

_FUNCTIONS: list[type] = [*SCALAR_FUNCTIONS, *TABLE_FUNCTIONS]

_DOCGEN_CATALOG = Catalog(
    name="docgen",
    default_schema="main",
    schemas=[
        Schema(
            name="main",
            comment="Merge SQL data into DOCX templates -> filled documents (DOCX/PDF) as BLOBs",
            functions=list(_FUNCTIONS),
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
