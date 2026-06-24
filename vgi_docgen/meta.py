"""Shared helpers for the per-object discovery/description metadata.

The ``vgi-lint`` strict profile expects these on **every** function and table.
Each function/table surfaces them in its ``Meta.tags``:

- ``vgi.title`` (VGI124)          -- human-friendly display name (must NOT
  normalize-equal the machine name, or VGI125 fires).
- ``vgi.doc_llm`` (VGI112)        -- a Markdown narrative aimed at LLM/agents.
- ``vgi.doc_md`` (VGI113)         -- a Markdown narrative for human docs.
- ``vgi.keywords`` (VGI126)        -- comma-separated search terms/synonyms.
- ``vgi.source_url`` (VGI128)      -- link to the implementing source file.

:func:`source_url` builds the canonical GitHub blob URL for a source file so
every object points at exactly where it is implemented; :func:`object_tags`
assembles the five standard per-object tags.
"""

from __future__ import annotations

# Base GitHub blob URL for source files in this repo (pinned to ``main``).
_SOURCE_BASE = "https://github.com/Query-farm/vgi-docgen/blob/main"


def source_url(relative_path: str) -> str:
    """Build the implementation ``vgi.source_url`` for a repo-relative file.

    Args:
        relative_path: Path relative to the repository root, e.g.
            ``vgi_docgen/scalars.py``.

    Returns:
        The canonical GitHub blob URL for that file on ``main``.
    """
    return f"{_SOURCE_BASE}/{relative_path}"


def object_tags(
    title: str,
    description_llm: str,
    description_md: str,
    keywords: str,
    relative_path: str,
) -> dict[str, str]:
    """Build the five standard per-object discovery/description tags.

    Args:
        title: Human-friendly display name (VGI124).
        description_llm: Markdown narrative for LLM/agent audiences (VGI112).
        description_md: Markdown narrative for human docs (VGI113).
        keywords: Comma-separated search terms/synonyms (VGI126).
        relative_path: Implementing source file, relative to the repo root,
            turned into the ``vgi.source_url`` (VGI128).

    Returns:
        A ``dict`` of the five ``vgi.*`` tags, ready to spread into a
        function's ``Meta.tags``.
    """
    return {
        "vgi.title": title,
        "vgi.doc_llm": description_llm,
        "vgi.doc_md": description_md,
        "vgi.keywords": keywords,
        "vgi.source_url": source_url(relative_path),
    }
