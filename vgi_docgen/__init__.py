"""DOCX mail-merge / document generation as a VGI worker for DuckDB/SQL.

The inverse of vgi-tika / vgi-pdf: merge query data *into* DOCX templates to
produce filled documents, each returned as a BLOB. The implementation is split
so each concern stays focused:

- ``core``        -- pure document logic (docxtpl render, docxcompose merge,
  optional LibreOffice PDF); bytes in, bytes out; no Arrow or VGI; unit-testable.
- ``scalars``     -- the per-row ``docgen_render`` scalar overloads (template as
  a VARCHAR path or a BLOB; data as an arbitrary STRUCT; optional PDF flag).
- ``buffering``   -- the single-bucket Sink+Source plumbing the merge path shares.
- ``tables``      -- the buffering ``docgen_merge`` (many rows -> one document).

``docgen_worker.py`` at the repo root assembles these into the ``docgen``
catalog and runs the worker over stdio (or HTTP).
"""

from __future__ import annotations

__version__ = "0.1.0"
