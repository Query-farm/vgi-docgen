"""End-to-end tests for the ``docgen_render`` scalar over the real RPC wire.

Spawns ``docgen_worker.py`` as a subprocess via ``vgi.client.Client`` and calls
the scalar exactly as DuckDB would after ATTACH, exercising both template
overloads (VARCHAR path / BLOB bytes), the arbitrary STRUCT data argument, and
NULL / hostile-input degradation to NULL.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pytest
from vgi import Arguments
from vgi.client import Client

from . import fixtures as fx

_WORKER = str(Path(__file__).resolve().parent.parent / "docgen_worker.py")

# STRUCT type matching the data we pass: customer/total strings + items list.
_ITEM_TYPE = pa.struct([("name", pa.string()), ("price", pa.string())])
_DATA_TYPE = pa.struct(
    [
        ("customer", pa.string()),
        ("total", pa.string()),
        ("items", pa.list_(_ITEM_TYPE)),
    ]
)


@pytest.fixture(scope="module")
def client() -> Iterator[Client]:
    # worker_limit=1 so output order matches input order for per-row assertions.
    with Client(f"{sys.executable} {_WORKER}", worker_limit=1) as c:
        yield c


def _render(client: Client, template_col: pa.Array, data_rows: list) -> list:
    batch = pa.RecordBatch.from_pydict(
        {
            "template": template_col,
            "data": pa.array(data_rows, type=_DATA_TYPE),
        }
    )
    results = list(
        client.scalar_function(
            function_name="docgen_render",
            input=iter([batch]),
            arguments=Arguments(positional=[]),
        )
    )
    return results[0]["result"].to_pylist()


def _row(customer: str, total: str) -> dict:
    return {"customer": customer, "total": total, "items": fx.KNOWN_ITEMS}


class TestRenderBytes:
    def test_renders_and_substitutes(self, client: Client) -> None:
        tpl = fx.make_template_bytes()
        out = _render(
            client,
            pa.array([tpl, tpl, None], type=pa.binary()),
            [_row(fx.KNOWN_CUSTOMER, fx.KNOWN_TOTAL), _row("Babbage", "1.00"), _row("X", "0")],
        )
        # Two rendered docs, third (NULL template) -> NULL.
        assert out[0] is not None and out[0][:4] == b"PK\x03\x04"
        assert out[1] is not None and out[1][:4] == b"PK\x03\x04"
        assert out[2] is None
        assert fx.KNOWN_CUSTOMER in fx.docx_text(out[0])
        assert fx.KNOWN_TOTAL in fx.docx_text(out[0])
        assert "Babbage" in fx.docx_text(out[1])

    def test_loop_items_present(self, client: Client) -> None:
        tpl = fx.make_template_bytes()
        out = _render(client, pa.array([tpl], type=pa.binary()), [_row("Y", "5")])
        text = fx.docx_text(out[0])
        for item in fx.KNOWN_ITEMS:
            assert item["name"] in text

    def test_garbage_template_is_null(self, client: Client) -> None:
        out = _render(
            client,
            pa.array([fx.make_garbage_bytes()], type=pa.binary()),
            [_row("Z", "0")],
        )
        assert out[0] is None


class TestRenderPath:
    """The VARCHAR-path overload, over a committed on-disk template."""

    def test_render_from_path(self, client: Client, tmp_path) -> None:
        tpl_path = tmp_path / "invoice.docx"
        fx.make_template_file(str(tpl_path))
        out = _render(
            client,
            pa.array([str(tpl_path)], type=pa.string()),
            [_row(fx.KNOWN_CUSTOMER, fx.KNOWN_TOTAL)],
        )
        assert out[0] is not None and out[0][:4] == b"PK\x03\x04"
        assert fx.KNOWN_CUSTOMER in fx.docx_text(out[0])

    def test_missing_path_is_null(self, client: Client) -> None:
        out = _render(
            client,
            pa.array(["/no/such/file.docx"], type=pa.string()),
            [_row("Z", "0")],
        )
        assert out[0] is None
