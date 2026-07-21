# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.16.0",
#     "docxtpl>=0.16",
#     "docxcompose>=1.4",
#     "python-docx>=1.1",
#     "pyarrow",
# ]
# ///
"""Stdio entry shim for the docgen VGI worker.

Lets the worker run straight from a source checkout (``uv run
docgen_worker.py``) and keeps ``import docgen_worker`` working for tests. The
implementation lives in ``vgi_docgen.worker``; installed users invoke the
``vgi-docgen`` console script (which points at ``vgi_docgen.worker:main``).

    ATTACH 'docgen' (TYPE vgi, LOCATION 'uv run docgen_worker.py');
    SELECT docgen.docgen_render('invoice.docx', {total: amt}) FROM inv;
"""

from vgi_docgen.worker import DocgenWorker, main

__all__ = ["DocgenWorker", "main"]

if __name__ == "__main__":
    main()
