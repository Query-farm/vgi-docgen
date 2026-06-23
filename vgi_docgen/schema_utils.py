"""Shared Arrow helpers for the docgen worker.

A column-comment helper (so output/relation schemas are self-documenting under
DuckDB ``DESCRIBE`` / ``duckdb_columns()``) plus context coercion that turns an
Arrow ``STRUCT`` row -- or a whole relation's rows -- into the plain Python
dicts ``docxtpl`` renders against.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa


def field(
    name: str,
    type: pa.DataType,
    comment: str,
    *,
    nullable: bool = True,
) -> pa.Field:
    """Build a ``pa.Field`` carrying a column comment in its metadata.

    DuckDB surfaces the ``comment`` metadata key via ``duckdb_columns()`` and
    ``DESCRIBE``.
    """
    return pa.field(
        name,
        type,
        nullable=nullable,
        metadata={b"comment": comment.encode("utf-8")},
    )


def to_context(value: Any) -> dict[str, Any]:
    """Coerce one decoded Arrow STRUCT scalar (a dict) into a render context.

    ``StructArray.to_pylist()`` already yields ``dict``s; this normalises a
    ``None`` (NULL struct) to an empty context and guarantees a plain ``dict``
    with string keys, recursively, so nested ``{% for %}`` data survives.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"expected a STRUCT (dict) row, got {type(value).__name__}")
    return {str(k): _clean(v) for k, v in value.items()}


def _clean(value: Any) -> Any:
    """Recursively normalise decoded Arrow values for Jinja rendering."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value
