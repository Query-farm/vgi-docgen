"""In-process tests for the buffering ``docgen_merge`` table function.

Drives the real bind -> sink -> combine -> finalize lifecycle via the harness,
templating against an on-disk template under a temp templates dir.
"""

from __future__ import annotations

import pyarrow as pa

from vgi_docgen.tables import DocgenMerge

from . import fixtures as fx
from .harness import run_buffering


def _input_table() -> pa.Table:
    return pa.table(
        {
            "customer": ["Ada", "Babbage", "Hopper"],
            "total": ["1.00", "2.00", "3.00"],
        }
    )


def test_merge_emits_one_blob_with_all_rows(tmp_path, monkeypatch) -> None:
    fx.make_template_file(str(tmp_path / "invoice.docx"))
    monkeypatch.setenv("VGI_DOCGEN_TEMPLATES", str(tmp_path))

    result = run_buffering(
        DocgenMerge,
        _input_table(),
        named={"template": "invoice.docx", "pdf": False},
    )

    assert result.num_rows == 1
    blob = result.column("doc")[0].as_py()
    assert blob[:4] == b"PK\x03\x04"  # one merged .docx
    text = fx.docx_text(blob)
    assert "Ada" in text and "Babbage" in text and "Hopper" in text


def test_merge_empty_relation_still_one_doc(tmp_path, monkeypatch) -> None:
    fx.make_template_file(str(tmp_path / "invoice.docx"))
    monkeypatch.setenv("VGI_DOCGEN_TEMPLATES", str(tmp_path))

    empty = pa.table({"customer": pa.array([], type=pa.string())})
    result = run_buffering(DocgenMerge, empty, named={"template": "invoice.docx", "pdf": False})
    assert result.num_rows == 1
    assert result.column("doc")[0].as_py()[:4] == b"PK\x03\x04"
