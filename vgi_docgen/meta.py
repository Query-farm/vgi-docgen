"""Shared helpers for the per-object discovery/description metadata.

The ``vgi-lint`` strict profile expects these on **every** function and table.
Each function/table surfaces them in its ``Meta.tags``:

- ``vgi.title`` (VGI124)          -- human-friendly display name (must NOT
  normalize-equal the machine name, or VGI125 fires).
- ``vgi.doc_llm`` (VGI112)        -- a Markdown narrative aimed at LLM/agents.
- ``vgi.doc_md`` (VGI113)         -- a Markdown narrative for human docs.
- ``vgi.keywords`` (VGI126/138)   -- a JSON array of search-term/synonym
  strings.

``vgi.source_url`` is deliberately NOT set per object: VGI139 wants
``source_url`` only on the catalog object, so the per-object tags omit it.
:func:`keywords_json` normalizes a comma-separated term list into the required
JSON-array form; :func:`object_tags` assembles the four standard per-object
tags.
"""

from __future__ import annotations

import json


def keywords_json(keywords: str) -> str:
    """Serialize a comma-separated keyword list as a JSON array of strings.

    Args:
        keywords: Comma-separated search terms/synonyms, e.g. ``"docx, word"``.

    Returns:
        A JSON array string like ``["docx","word"]`` as VGI138 requires for
        ``vgi.keywords`` (a JSON array, never a bare comma-separated string).
    """
    terms = [term.strip() for term in keywords.split(",") if term.strip()]
    return json.dumps(terms)


def object_tags(
    title: str,
    description_llm: str,
    description_md: str,
    keywords: str,
    relative_path: str,
) -> dict[str, str]:
    """Build the four standard per-object discovery/description tags.

    Args:
        title: Human-friendly display name (VGI124).
        description_llm: Markdown narrative for LLM/agent audiences (VGI112).
        description_md: Markdown narrative for human docs (VGI113).
        keywords: Comma-separated search terms/synonyms, serialized to the
            JSON-array form VGI138 requires (VGI126).
        relative_path: Implementing source file, relative to the repo root.
            Accepted for call-site documentation but intentionally unused:
            VGI139 wants ``source_url`` only on the catalog object, so no
            per-object ``vgi.source_url`` is emitted.

    Returns:
        A ``dict`` of the four ``vgi.*`` tags, ready to spread into a
        function's ``Meta.tags``.
    """
    del relative_path  # per-object source_url omitted (VGI139)
    return {
        "vgi.title": title,
        "vgi.doc_llm": description_llm,
        "vgi.doc_md": description_md,
        "vgi.keywords": keywords_json(keywords),
    }
