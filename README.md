<p align="center">
  <img src="https://raw.githubusercontent.com/Query-farm/vgi/main/docs/vgi-logo.png" alt="Vector Gateway Interface (VGI)" width="320">
</p>

<p align="center"><em>A <a href="https://query.farm">Query.Farm</a> VGI worker for DuckDB.</em></p>

# vgi-docgen

A [VGI](https://query.farm) worker that brings **mail-merge at scale from SQL**
to DuckDB: merge query data *into* DOCX templates to produce filled documents —
invoices, contracts, statements, letters — each returned as a **BLOB**. It is the
inverse of [vgi-tika](https://query.farm) / [vgi-pdf](https://query.farm): those
pull text/structure *out* of documents; this fills documents *up*.

Backed by [docxtpl](https://docxtpl.readthedocs.io/) (Jinja2-style
`{{ placeholders }}` and `{% for %}` loops over [python-docx](https://python-docx.readthedocs.io/),
both LGPL/MIT) and [docxcompose](https://pypi.org/project/docxcompose/) (BSD) for
the merge. PDF output is **optional** and uses headless LibreOffice if present.

```sql
INSTALL vgi FROM community; LOAD vgi;
ATTACH 'docgen' (TYPE vgi, LOCATION 'uv run docgen_worker.py');

-- One rendered DOCX per row (scalar): template + a STRUCT of row data -> BLOB
SELECT docgen.docgen_render('invoice.docx', {customer: name, total: amount})
FROM invoices;

-- Inline template bytes work too (BLOB template instead of a path)
SELECT docgen.docgen_render(tpl.bytes, {customer: name})
FROM letters, templates AS tpl;

-- Opt into PDF (3rd positional arg; requires headless LibreOffice on PATH)
SELECT docgen.docgen_render('invoice.docx', {total: amount}, true) FROM invoices;

-- Many rows -> ONE merged document (buffering): template as a NAMED arg
SELECT doc FROM docgen.docgen_merge(
    (SELECT customer, total FROM invoices),
    template := 'invoice.docx');
```

## Functions

| function | kind | signature | returns |
|----------|------|-----------|---------|
| `docgen_render(template, data)` | scalar | template `VARCHAR` path **or** `BLOB` bytes; `data` a `STRUCT` | rendered `.docx` `BLOB` (NULL on failure) |
| `docgen_render(template, data, pdf)` | scalar | + `pdf BOOLEAN` | `.docx` or `.pdf` `BLOB` (NULL if PDF requested but LibreOffice absent) |
| `docgen_merge(rel, template[, pdf])` | table (buffering) | `rel` a `(SELECT …)`; `template := 'path'` named; `pdf := true` named | one-row `doc BLOB` — all rows merged into a single document |

### `docgen_render` — one document per row (scalar)

A true DuckDB **scalar**, so it composes in any projection. Arguments are
**positional only** (scalar functions do not support `name := value`):

1. **template** — a `VARCHAR` path (resolved directly, then under
   `$VGI_DOCGEN_TEMPLATES`) **or** a `BLOB` of raw `.docx` bytes. These are two
   overloads sharing the name, resolved by argument type.
2. **data** — an arbitrary `STRUCT`. Every field becomes a Jinja2 variable in the
   template (`{{ field }}`); nested `STRUCT`/`LIST` data drives `{% for %}` loops
   and tables. Build it inline with `{a: x, b: y}` or `struct_pack(a := x)`.
3. **pdf** *(optional)* — `BOOLEAN`; `true` converts to PDF via LibreOffice.

### `docgen_merge` — many rows into one document (buffering)

The mail-merge path: renders the template once per input row and concatenates the
results into a **single** merged `.docx` (a page break between rows), returned as
one BLOB. Because it must see every row first, it is a **buffering**
(Sink/finalize) table function: the relation is the positional `(SELECT …)`, and
the `template` (and optional `pdf`) are **named** args (table functions support
`name := value`). Every relation column is available to the template by name.

## Templates

- **Path** — `'invoice.docx'`. Resolved relative to the worker's working
  directory, then under `$VGI_DOCGEN_TEMPLATES` if set, so you can keep a shared
  templates directory and reference bare names.
- **Inline bytes** — pass a `BLOB` column of raw `.docx` bytes (e.g. a templates
  table). Lets templates live in DuckDB itself.

Templates are ordinary `.docx` files authored in Word/LibreOffice with
[docxtpl](https://docxtpl.readthedocs.io/) tags: `{{ customer }}`,
`{% for item in items %} … {% endfor %}`, `{%tr %}` for table-row loops, etc.

## Robustness (untrusted-binary discipline)

The scalar path treats a NULL template/data, a non-`.docx` (non-ZIP) blob, a
malformed template, a Jinja render error, or a requested-but-unavailable PDF
conversion as **NULL** output — never a worker crash. The merge path surfaces the
same failures as a **clean DuckDB error** (so a typo'd template name is visible,
not silently empty). Every `.docx` is magic-checked (`PK\x03\x04`) before
docxtpl touches it.

## PDF output (optional)

DOCX is the clean, dependency-light **default**. PDF conversion shells out to a
headless **LibreOffice** (`soffice`/`libreoffice` on PATH, or `$VGI_DOCGEN_SOFFICE`).
LibreOffice is **not** a dependency of this package — if it is absent, the scalar
PDF path yields NULL and the merge PDF path raises a clear error. DOCX→PDF
fidelity is whatever LibreOffice produces.

## Development

```sh
uv sync --extra dev
uv run --no-sync pytest -q                 # pure core + in-proc + Client RPC E2E
make test-sql                              # haybarn-unittest SQL E2E (authoritative)
uv run --no-sync ruff check . && uv run --no-sync mypy vgi_docgen/
```

## Caveats

- **DOCX→PDF needs LibreOffice** (heavy, optional, slower); without it, stick to
  DOCX output. Fidelity is LibreOffice's, not Word's.
- **Large BLOBs through Arrow have a practical size ceiling.** A merge of
  thousands of rich documents into one file can grow large; prefer per-row
  `docgen_render` (or batch the merge) for very large jobs.
- **Template complexity is the support burden.** Simple `{{ }}` substitution is
  trivial; loops, tables, and embedded images depend on correctly-authored
  docxtpl templates and are where most issues live.

## Licensing

This worker is **MIT**. Dependencies are permissive:

- **docxtpl** — LGPL-2.1 (used as a library, not modified/vendored).
- **python-docx** — MIT.
- **docxcompose** — BSD-3-Clause.
- **Jinja2** (via docxtpl) — BSD-3-Clause.
- **pyarrow** — Apache-2.0.
- **LibreOffice** — MPL-2.0 / LGPL-3.0, and only an **optional runtime**
  dependency for the PDF path (never bundled, never imported; invoked as an
  external process only when you opt into PDF output).

---

## Authorship & License

Written by [Query.Farm](https://query.farm).

Copyright 2026 Query Farm LLC - https://query.farm

