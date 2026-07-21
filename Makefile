# vgi-docgen — dev and test targets.
#
# Usage:
#   make test       # unit/integration (pytest) + end-to-end SQL (haybarn-unittest)
#   make test-unit  # pytest only
#   make test-sql   # DuckDB sqllogictest .test files via haybarn-unittest
#
# test-sql is self-contained: it points VGI_DOCGEN_WORKER at the worker run as a
# uv stdio subprocess (exactly how DuckDB drives it after ATTACH) and runs the
# files under test/sql/. haybarn-unittest is a uv tool:
#   uv tool install haybarn-unittest   # installs ~/.local/bin/haybarn-unittest

# Worker command DuckDB uses for ATTACH (overridable). Use the installed console
# script in the project venv (NOT `uv run docgen_worker.py`): the PEP-723 script
# env caches a stale SDK and can emit an old catalog schema, so drive the worker
# through the venv python that `uv sync` provisions.
WORKER_STDIO    ?= .venv/bin/vgi-docgen

# haybarn-unittest lives in the uv tools bin; keep it on PATH.
HAYBARN_BIN     ?= $(HOME)/.local/bin
TEST_DIR         = .
TEST_PATTERN     = test/sql/*

.PHONY: test test-unit test-sql lint

test: test-unit test-sql

test-unit:
	uv run pytest -q

test-sql:
	PATH="$(HAYBARN_BIN):$$PATH" \
		VGI_DOCGEN_WORKER="$(WORKER_STDIO)" \
		haybarn-unittest --test-dir "$(TEST_DIR)" "$(TEST_PATTERN)"

lint:
	uv run --no-sync ruff format --check .
	uv run --no-sync ruff check .
	uv run --no-sync mypy vgi_docgen/
