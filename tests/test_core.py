"""Unit tests for the pure document-generation core (no Arrow / VGI)."""

from __future__ import annotations

import pytest

from vgi_docgen import core
from vgi_docgen.core import DocgenError, TemplateRef

from . import fixtures as fx


def test_render_substitutes_placeholders() -> None:
    ref = TemplateRef.from_bytes(fx.make_template_bytes())
    assert ref is not None
    out = core.render_docx(ref, {"customer": fx.KNOWN_CUSTOMER, "total": fx.KNOWN_TOTAL, "items": []})
    text = fx.docx_text(out)
    assert fx.KNOWN_CUSTOMER in text
    assert fx.KNOWN_TOTAL in text
    assert out[:4] == b"PK\x03\x04"  # valid .docx ZIP


def test_render_expands_loop() -> None:
    ref = TemplateRef.from_bytes(fx.make_template_bytes())
    assert ref is not None
    out = core.render_docx(ref, {"customer": "X", "total": "0", "items": fx.KNOWN_ITEMS})
    text = fx.docx_text(out)
    for item in fx.KNOWN_ITEMS:
        assert item["name"] in text
        assert item["price"] in text


def test_merge_concatenates_rows() -> None:
    ref = TemplateRef.from_bytes(fx.make_template_bytes())
    assert ref is not None
    merged = core.merge_docx(
        ref,
        [
            {"customer": "Ada", "total": "1", "items": []},
            {"customer": "Babbage", "total": "2", "items": []},
        ],
    )
    text = fx.docx_text(merged)
    assert "Ada" in text and "Babbage" in text
    assert merged[:4] == b"PK\x03\x04"


def test_merge_empty_yields_valid_docx() -> None:
    ref = TemplateRef.from_bytes(fx.make_template_bytes())
    assert ref is not None
    merged = core.merge_docx(ref, [])
    assert merged[:4] == b"PK\x03\x04"


def test_garbage_bytes_rejected() -> None:
    with pytest.raises(DocgenError):
        TemplateRef.from_bytes(fx.make_garbage_bytes())


def test_missing_path_rejected() -> None:
    with pytest.raises(DocgenError):
        TemplateRef.from_path("/no/such/template.docx")


def test_null_passes_through() -> None:
    assert TemplateRef.from_bytes(None) is None
    assert TemplateRef.from_path(None) is None


def test_path_resolves_under_templates_dir(tmp_path) -> None:
    fx.make_template_file(str(tmp_path / "invoice.docx"))
    ref = TemplateRef.from_path("invoice.docx", templates_dir=str(tmp_path))
    assert ref is not None
    out = core.render_docx(ref, {"customer": "Z", "total": "0", "items": []})
    assert "Z" in fx.docx_text(out)


def test_pdf_without_libreoffice_is_clean_error(monkeypatch) -> None:
    # Force "no LibreOffice" regardless of host.
    monkeypatch.setattr(core, "_soffice_path", lambda: None)
    assert core.libreoffice_available() is False
    with pytest.raises(DocgenError, match="LibreOffice"):
        core.to_pdf(b"PK\x03\x04 whatever")
