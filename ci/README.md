# CI: the vgi-docgen worker integration suite

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs the unit tests
and this repo's sqllogictest suite (`test/sql/*.test`) against the vgi-docgen
VGI worker through the **real DuckDB `vgi` extension** on every push / PR.

## How it works (no C++ build)

Rather than building the vgi DuckDB extension from source, CI drives a
**prebuilt** standalone `haybarn-unittest` (the DuckDB/Haybarn sqllogictest
runner, published in Haybarn's releases) and installs the **signed** `vgi`
extension from the Haybarn community channel:

1. **Install the worker** — `uv sync --frozen` into a venv. `.venv/bin/vgi-docgen`
   is a self-contained PEP 723 stdio worker the extension can spawn via
   `uv run .venv/bin/vgi-docgen`.
2. **Download the runner** — the matching `haybarn_unittest-*` asset per
   platform from the latest Haybarn release.
3. **Preprocess** — the standalone runner links none of the extensions the
   tests gate on, so [`preprocess-require.awk`](preprocess-require.awk) rewrites
   each `require <ext>` into an explicit signed `INSTALL <ext> FROM
   {community,core}; LOAD <ext>;`. These tests skip `require vgi` (haybarn
   silently SKIPs it) and `LOAD vgi;` directly, so the awk also injects an
   `INSTALL vgi FROM community;` right before each bare `LOAD vgi;`. `require-env`
   and everything else pass through untouched.
4. **Run** — [`run-integration.sh`](run-integration.sh) stages the preprocessed
   tree (including the committed DOCX template fixtures under `test/sql/data/`,
   which the tests read by relative path), points `VGI_DOCGEN_WORKER` at the
   worker LOCATION, warms the extension cache once, then runs the suite in a
   single `haybarn-unittest` invocation, with a guard against silent skips (see
   below). Any failed assertion exits non-zero and fails the job.

## Three transports (one suite)

The vgi extension picks its transport from the ATTACH `LOCATION` string. The
SAME `test/sql/*.test` suite runs over all three, selected by the `TRANSPORT`
env var (default `subprocess`); the CI `integration` job is a
`transport: [subprocess, http, unix]` × `os: [ubuntu, macos]` matrix:

- **subprocess** (stdio) — `VGI_DOCGEN_WORKER=.venv/bin/vgi-docgen`; the
  extension spawns the worker per query and talks Arrow IPC over stdin/stdout.
- **http** — `run-integration.sh` boots `vgi-docgen --http --port 0 --port-file
  <f>` (cwd = the stage dir, so it resolves the staged `test/sql/data/*.docx`
  fixtures), polls the port-file, and sets
  `VGI_DOCGEN_WORKER=http://127.0.0.1:<port>` (bare scheme://host:port, no path).
  The HTTP transport rides DuckDB's `httpfs`, so the script injects
  `INSTALL httpfs FROM core; LOAD httpfs;` after each `LOAD vgi;` in the staged
  tests (http leg only). Needs the `http` extra (waitress) — the job installs it
  with `uv sync --extra http`.
- **unix** — boots `vgi-docgen --unix <sock>` (cwd = stage dir), polls for the
  socket, sets `VGI_DOCGEN_WORKER=unix://<sock>`.

**Silent-skip guard.** The DuckDB/Haybarn sqllogictest runner SKIPS (exit 0!)
any test whose error message contains "HTTP" / "Unable to connect", so a broken
http setup would report "All tests were skipped" and go GREEN having tested
nothing. The run step captures the report and fails the leg if it sees
`All tests were skipped`.

## Run it locally

```bash
uv sync --python 3.13                       # install the worker + deps
# point HAYBARN_UNITTEST at a haybarn-unittest binary (or a local DuckDB
# `unittest` built with the vgi extension), and the worker at the stdio command:
HAYBARN_UNITTEST=/path/to/haybarn-unittest \
VGI_DOCGEN_WORKER="uv run --python 3.13 .venv/bin/vgi-docgen" \
  ci/run-integration.sh
```

Or use the Makefile target `make test-sql`, which installs `haybarn-unittest`
as a uv tool and points the worker at `uv run --python 3.13 .venv/bin/vgi-docgen`.
