# CLAUDE.md — vgi-docgen

Contributor/agent notes. User-facing docs live in `README.md`; this is the
"how it's built and where the sharp edges are" companion. Sibling style/tooling
to `vgi-pdf` (BLOB output, untrusted-binary discipline) and `vgi-statsmodels`
(the whole-relation buffering Sink/finalize data-flow).

## What this is

A [VGI](https://query.farm) worker that does the **inverse of vgi-tika /
vgi-pdf**: instead of pulling text/structure *out* of documents, it merges SQL
query data *into* DOCX templates to produce filled documents (invoices,
contracts, statements, letters), each returned as a **BLOB**. Backed by
[docxtpl](https://docxtpl.readthedocs.io/) (Jinja2 over
[python-docx](https://python-docx.readthedocs.io/)) for rendering and
[docxcompose](https://pypi.org/project/docxcompose/) for the merge.
`docgen_worker.py` assembles every function into one `docgen` catalog (single
`main` schema) over stdio.

## Layout

```
docgen_worker.py     repo-root stdio entry shim; PEP 723 inline deps; main()
vgi_docgen/
  core.py            pure bytes->bytes: docxtpl render, docxcompose merge,
                     optional LibreOffice PDF; no Arrow/VGI; unit-testable
  scalars.py         docgen_render scalar overloads (path/bytes template,
                     STRUCT data, optional pdf flag) -> BLOB
  buffering.py       SinkBuffer (single-bucket sink/combine) + Arrow plumbing;
                     reassembles sunk rows into a list of render-context dicts
  tables.py          docgen_merge (TableBufferingFunction): many rows -> one doc
  discovery.py       sample_templates browsable table: bundled templates + their
                     path/fields (fields derived from the .docx at scan time)
  schema_utils.py    pa.Field comment helper + STRUCT-row -> render-context coercion
  worker.py          assembles the catalog; main() / main_http()
tests/               pytest: test_core (pure), test_tables (in-proc merge), test_scalars (Client RPC)
test/sql/*.test      haybarn-unittest sqllogictest — authoritative E2E
test/sql/data/       committed deterministic .docx template + a garbage fixture
Makefile             test / test-unit / test-sql / lint
```

To add a function: implement the math in `core.py` (pure, bytes in/out, raising
`DocgenError` on bad input), then add a `ScalarFunction` overload in `scalars.py`
(or a `SinkBuffer` subclass in `tables.py`), and append it to `SCALAR_FUNCTIONS`
/ `TABLE_FUNCTIONS`.

## VGI conventions that bit us (read before editing)

1. **Scalars are POSITIONAL-only.** `docgen_render` takes its template and data
   positionally; the `name := value` syntax is a *table-function* property. The
   merge path (`docgen_merge`) is a table function, so it *can* and *does* take
   `template := '...'` / `pdf := true` as named args.

2. **BLOB returns need explicit `Returns(arrow_type=pa.binary())`** — every
   `compute()` and the merge output schema declares `pa.binary()` explicitly.

3. **A STRUCT *input* param cannot be annotated `pa.StructArray` with only a
   `type_bound`.** The SDK's `_param_to_arg` rejects `pa.StructArray` (a
   COMPLEX_ARRAY_CLASS) unless you give a concrete `arrow_type` — but the data
   struct's shape varies per call. The working pattern is to annotate the param
   as **`pa.Array`** (the generic = AnyArrow path) with
   `Param(type_bound=pa.types.is_struct)`: arrow_type stays dynamic, the struct
   type is resolved at bind from the actual column, and `compute` receives the
   real `StructArray` (`.to_pylist()` → row dicts). `_struct_rows` also unwraps a
   possible `AnyArrowValue` (`.value`) defensively.

4. **Overloads share one `Meta.name`, set EXPLICITLY in each `class Meta`.** The
   path/bytes/pdf variants are four `ScalarFunction` subclasses all naming
   themselves `docgen_render`. Do **not** factor `name` into a shared base
   `Meta` class — the SDK derives the function name from the class name unless
   `name` is set directly on that class's own `Meta`, so a base-class `name`
   silently produces `docgen_render_path` etc. and breaks the overload.

5. **`haybarn-unittest` silently SKIPS `require vgi`.** Under haybarn the
   extension isn't autoloaded for `require`, so a `.test` using `require vgi` is
   SKIPPED, not run. Use explicit `statement ok` / `LOAD vgi;` (the `.test`
   here does), `require-env VGI_DOCGEN_WORKER`, and ATTACH via
   `${VGI_DOCGEN_WORKER}`. Run with the GLOB `test/sql/*`.

6. **`LENGTH` doesn't take BLOB in DuckDB; use `OCTET_LENGTH`.** And to magic-
   check the ZIP header, compare a slice to a BLOB literal: `doc[1:2] = 'PK'::BLOB`.

## Buffering (the merge path) — one relation in, one document out

`docgen_merge` must see *every* row before it can produce its single merged
document, so it's a `TableBufferingFunction` (Sink+Source), routed through the
C++ `PhysicalVgiTableBuffering` operator:

- `process(batch)` — sink each input batch to execution-scoped `BoundStorage`.
- `combine(state_ids)` — collapse to a single finalize key (one bucket).
- `finalize(...)` — `buffered_contexts()` reassembles the full input as a list of
  per-row context dicts, render+merge once, emit one BLOB row, then `out.finish()`.

`SinkBuffer` in `buffering.py` implements `process`/`combine`/`buffered_contexts`;
the function only writes `on_bind` (output schema) + `finalize`. A
`DrainState(done: bool)` cursor makes finalize emit exactly once.

**Empty input relation → zero output rows.** With no input batches the C++
operator never drives `process`/`finalize`, so an empty `(SELECT … WHERE false)`
yields an empty result set (no document) — the `.test` asserts `count(*) = 0`,
not one empty doc. (The in-proc harness, which explicitly calls
combine/finalize, *does* emit the empty-context document — a harness artifact,
not the wire behaviour.)

## Untrusted-binary discipline

Every `.docx` is magic-checked (`PK\x03\x04` ZIP header) before docxtpl opens
it. The **scalar** path funnels a NULL template/data, a non-DOCX blob, a
malformed template, a Jinja render error, and a requested-but-unavailable PDF
conversion all to **NULL** output — never an unhandled crash. The **merge** path
surfaces the same failures as a **clean DuckDB error** (a typo'd template name
should be visible, not a silently empty file). The `.test` asserts the worker is
still alive and serving after a merge error.

## PDF output (optional, never a hard dep)

DOCX is the clean default. `core.to_pdf` shells out to a headless LibreOffice
(`soffice`/`libreoffice` on PATH, or `$VGI_DOCGEN_SOFFICE`) in a temp dir and is
the only place a subprocess is spawned. LibreOffice is **not** a Python
dependency and is **never imported** — if it's absent, the scalar PDF path
yields NULL and the merge PDF path raises `DocgenError`. CI does not install
LibreOffice, so the PDF path is exercised only by `test_core`'s
"no-LibreOffice → clean error" assertion (monkeypatched). Real DOCX→PDF fidelity
is whatever LibreOffice produces.

## Templates

Resolved from a `VARCHAR` ref (direct path, then under `$VGI_DOCGEN_TEMPLATES`)
or inline `BLOB` bytes. A new `DocxTemplate` is built per render — docxtpl
mutates its document in place, so a template is never shared across rows. The
committed `test/sql/data/invoice.docx` is a deterministic python-docx build
(byte-identical across runs, verified) with a `{{ placeholder }}` header and a
`{% for %}` loop; the unit suite builds its templates in-memory and writes only
to `tmp_path`, so the committed fixture never churns.

## Testing

```sh
uv sync --extra dev
uv run --no-sync pytest -q     # pure core + in-proc merge + Client RPC scalar E2E
make test-sql                  # haybarn-unittest over test/sql/*  (authoritative)
uv run --no-sync ruff check . && uv run --no-sync mypy vgi_docgen/
```

`make test-sql` sets `VGI_DOCGEN_WORKER="uv run --python 3.13 docgen_worker.py"`,
puts `~/.local/bin` on PATH, and runs `haybarn-unittest --test-dir . "test/sql/*"`.
Install the runner once with `uv tool install haybarn-unittest`. Everything is
offline/hermetic (no LibreOffice required).

## Licensing

The worker's own code is **MIT**. Dependencies are permissive: python-docx
(MIT), docxcompose (BSD-3), Jinja2 (BSD-3), docxtpl (LGPL-2.1, used as an
unmodified library), pyarrow (Apache-2.0). **LibreOffice** (MPL-2.0 / LGPL-3.0)
is an **optional runtime** dep for the PDF path only — invoked as an external
process, never bundled or imported. No vendoring, no patched deps.
