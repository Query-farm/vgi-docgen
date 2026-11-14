# Document generation notebooks

[01 · Reconcile SQL amounts with generated documents](01_reconcile_generated_documents.ipynb)
follows ten synthetic order lines into five customer summaries and one merged
DOCX. Exact decimal SQL owns calculation and rounding; the real worker renders and
merges. The notebook inspects returned document text and charts customer amounts
and actual compressed package sizes.

## Run independently

Install [uv](https://docs.astral.sh/uv/) and Git. This directory works when copied
away from the repository; no parent worker checkout or root environment is used.

```sh
uv sync --locked
uv run --locked python execute.py --timeout 300
```

The separate environment locks Haybarn **2.0.0rc11**, JupySQL and plotting tools.
A temporary kernel uses this interpreter and notebook-directory cwd. Execution
replaces the saved notebook atomically only after success. Overrides require a
separate output directory. Optionally register a kernel for a Jupyter frontend:

```sh
uv run --locked python -m ipykernel install --user \
  --name vgi-docgen-notebooks --display-name "Python (vgi-docgen notebooks)"
```

Restart and run all after parameter edits. The execution runner itself creates no
global kernel. First runs need package and extension downloads.

## Literal remote launch

The visible SQL uses:

```text
uvx --python 3.13 --with vgi-python==0.51.0 --with vgi-rpc==0.53.1 --with pyarrow==26.0.1 --with docxtpl==0.20.2 --with docxcompose==2.2.0 --with python-docx==1.2.0 --from git+https://github.com/Query-farm/vgi-docgen@v0.4.0 vgi-docgen
```

Remote tag **v0.4.0** resolves to **962d95bc0119361e6264d3bb9289346c60299ee0**.
Runtime pins match the worker's tested lock. uv installs the remote package in its
own cache; a local worker build is unnecessary. Its `sample_templates` table is
shown for discovery. The investigation uses the original
[companion template](templates/README.md) for explicit gross/discount/net fields.

The helper removes inherited `VGI_DOCGEN_TEMPLATES` while running, then restores
it. The relative template path resolves inside this directory. No account,
external API, real order, email or live data mode is involved.

## Data, units and rounding

All organizations, items and amounts are synthetic and visible in SQL. Prices
and totals use DECIMAL(12,2), quantity is integer and currency is USD. Tax and
shipping are outside this model. For each customer, sum quantity × unit price,
round that customer's gross × discount percentage to two decimals (half away
from zero), then subtract the rounded discount from gross. A separate query shows
why rounding one aggregate batch discount is a different policy.

The DOCX template performs no arithmetic: SQL passes customer ID/name, gross,
discount percent, discount and net as formatted strings. The worker's scalar
`docgen_render` produces one BLOB per context; buffering `docgen_merge` consumes
all contexts and emits one BLOB. Both are materialized before DataFrame capture,
so presentation does not repeat rendering.

ZIP CRC checks and direct document-XML inspection compare all eight nonempty
paragraphs per customer against SQL. A multiset comparison checks that the merged
file contains exactly one copy of each block; merge order is not assumed.
Python neither renders nor merges documents. ZIP headers and non-NULL outputs are
additional checks, not substitutes for content reconciliation.

## Focused experiment and generated files

```sh
uv run --locked python execute.py --timeout 300 \
  --parameters '{"DISCOUNT_PCT": 15}' --output-dir artifacts/discount-15
```

Change only **DISCOUNT_PCT**, default **10**, experiment **15**. Accepted values are
whole percentages **0–50**. Predict a lower net total with unchanged source gross,
customer count and document count. Compare the two rounding levels as well as the
amount chart and verified document text. Reset to **10**.

Six generated DOCX files are written under `artifacts/generated/discount-10pct/`
(or the selected percentage): C01–C05 plus `merged.docx`. The runner copies assets,
this guide, helpers, lock, templates and generated-document directories beside
experiment outputs. Failed execution leaves the successful default notebook
intact. Logs, generated files, charts and experiments are ignored; the primary
notebook retains embedded output.

## Limits and validation

This verifies synthetic content through DOCX output. It does not test real billing
rules or Word/LibreOffice pagination, fonts and complex layout. No PDF conversion
is requested and LibreOffice is not required. BLOB sizes measure this template's
ZIP packaging, not runtime performance or a general compression ratio. ZIP
metadata may differ between runs without changing document text.

The scalar invalid-template case returns NULL; the following valid render proves
recovery. Empty merge input produces zero output rows. Eight SQL invariants plus
recovery, per-document paragraph checks and merged multiplicity validate the flow.
Default and the detached discount experiment are executed and charts inspected.
Three runner guards verify preservation of successful output.

Repository checks: 16 pytest cases, 24 SQL assertions, Ruff lint/format, strict
mypy (9 source files), isolated `uvx pydoclint vgi_docgen` and metadata 100/100 L2 with zero findings pass.
The root environment's pydoclint has an existing `DocstringYields` import conflict;
the isolated checker passes without changing root dependencies.
To upgrade, change the literal Git tag/runtime pins, then rerun default and
experiment and inspect document content and charts before replacing outputs. The
community VGI extension is installed independently of the Python lock. The root
worker lock and source are unchanged.
