"""Formatting and DOCX inspection; SQL and the worker own arithmetic/rendering."""

from __future__ import annotations

import io
import os
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import matplotlib.pyplot as plt
import seaborn as sns
from IPython.display import Markdown, display


def configure(discount: int):
    if type(discount) is not int or not 0 <= discount <= 50:
        raise ValueError("DISCOUNT_PCT must be a whole percent from 0 through 50")
    previous = os.environ.pop("VGI_DOCGEN_TEMPLATES", None)
    directory = Path("artifacts/generated") / f"discount-{discount}pct"
    directory.mkdir(parents=True, exist_ok=True)
    return previous, directory, datetime.now(UTC).isoformat()


def cleanup(previous):
    if previous is None:
        os.environ.pop("VGI_DOCGEN_TEMPLATES", None)
    else:
        os.environ["VGI_DOCGEN_TEMPLATES"] = previous


def paragraphs(blob: bytes) -> list[str]:
    """Inspect the produced ZIP/XML; this never fills or merges a template."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        if archive.testzip() is not None:
            raise ValueError("DOCX ZIP CRC check failed")
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    return ["".join(p.itertext()) for p in root.findall(".//w:body/w:p", ns) if "".join(p.itertext())]


def inspect_documents(rows, merged: bytes, destination: Path):
    """Compare document paragraphs to SQL-formatted fields, independent of merge order."""
    expected_blocks = []
    checks = []
    for row in rows:
        customer_id, customer, gross, pct, discount, net, blob = row
        expected = [
            "SYNTHETIC ORDER SUMMARY",
            f"Customer ID: {customer_id}",
            f"Customer: {customer}",
            "Currency: USD; synthetic example; tax and shipping excluded.",
            f"Gross USD: {gross}",
            f"Discount {pct}% USD: {discount}",
            f"Net USD: {net}",
            "Demonstration only. No order is placed, billed or sent.",
        ]
        actual = paragraphs(blob)
        if actual != expected:
            raise ValueError(f"Rendered content differs from SQL for {customer_id}: {actual!r}")
        (destination / f"{customer_id}.docx").write_bytes(blob)
        expected_blocks.append(tuple(expected))
        checks.append({"customer_id": customer_id, "paragraphs_match_sql": True, "net_usd_text": net})
    text = paragraphs(merged)
    blocks = []
    for paragraph in text:
        if paragraph == "SYNTHETIC ORDER SUMMARY":
            blocks.append([])
        if not blocks:
            raise ValueError("Merged document has content outside an order summary")
        blocks[-1].append(paragraph)
    if Counter(map(tuple, blocks)) != Counter(expected_blocks):
        raise ValueError("Merged document omitted, duplicated or changed an order summary")
    (destination / "merged.docx").write_bytes(merged)
    return checks, text


def prose(text: str) -> None:
    display(Markdown(text))


def theme() -> None:
    sns.set_theme(
        style="whitegrid",
        rc={
            "figure.dpi": 145,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": "#E8EDE9",
            "text.color": "#243B2F",
            "axes.labelcolor": "#405047",
            "text.parse_math": False,
            "legend.frameon": False,
        },
    )


def chart(fig, title: str, subtitle: str, source: str) -> None:
    fig.text(0.08, 0.98, title, ha="left", va="top", fontsize=17, fontweight="semibold")
    fig.text(0.08, 0.90, subtitle, ha="left", va="top", fontsize=10, color="#58685F")
    fig.tight_layout(rect=(0.02, 0.11, 1, 0.82))
    fig.text(0.08, 0.03, source, fontsize=8, color="#6C7D73")
    plt.show()
