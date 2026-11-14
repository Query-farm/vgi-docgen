# DOCX Mail Merge example

[01 · Reconcile SQL amounts with generated documents](01_reconcile_generated_documents.ipynb)
follows ten synthetic order lines into five customer summaries and one merged
DOCX. Exact decimal SQL owns calculation and rounding; the real worker renders and
merges. A preview uses the bundled template registry to discover its two-field
contract and render one actual summary. The richer companion template then retains
the gross/discount/net breakdown. Returned XML text is checked before charting
customer amounts and compressed package sizes.

Read the saved notebook directly on GitHub, or choose **Open in Colab** and run the
install cell followed by Run All. A single downloaded notebook can retrieve the
SHA-256-verified inspection helper and template through shared `prepare("docgen")`, pinned to public companion commit
`f4bdde50f2ba378ad305bb297f2e698ad975bc06`.
No parent source checkout, Python worker build, API key or office application is
needed. Actual hosted Colab execution has not been tested; a fresh preloaded
Python 3.12 notebook-only run validates this bootstrap path.

## Locked local runner

Install [uv](https://docs.astral.sh/uv/) and Git, then run from this directory:

```sh
uv sync --locked --extra runner
uv run --locked --extra runner vgi-notebooks
```

The [shared tools v0.3.16](https://github.com/Query-farm/vgi-example-notebooks/tree/v0.3.16) supply SQL setup, branding and SVG presentation; the
optional `[runner]` extra is for local publication. Colab installs only the base
package and accepts compatible preloaded data/plotting libraries. The notebook
kernel supports Python 3.11+; uv selects a compatible Python interpreter for the
worker's separately isolated environment. No root dependency files are changed.

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'docgen' (TYPE vgi, LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-docgen@v0.4.0 vgi-docgen');
```

Public tag **v0.4.0** resolves to **962d95bc0119361e6264d3bb9289346c60299ee0**.
The clean command was exercised through published Haybarn **2.0.0rc11**, without
transitive `--with` overrides. Initial setup needs network access for packages,
extensions and public companions; all analytical data and generated files stay
local. `connect(globals())` creates an in-memory connection with empty temporary
SQL-secret storage, persistent secrets disabled and JupySQL default autoload off.
Cleanup closes it and removes the temporary secret directory.

The domain helper temporarily removes `VGI_DOCGEN_TEMPLATES` to keep path resolution
local, then restores the original setting at cleanup. Its ZIP/XML inspection
neither fills nor merges templates. The worker does all document generation.

Optional local kernel:

```sh
uv run --locked --extra runner python -m ipykernel install --user \
  --name vgi-docgen-notebooks --display-name "Python (vgi-docgen notebooks)"
```

## Data, discovery and rounding

All organizations, items and amounts are synthetic and visible in SQL. Prices
and totals use DECIMAL(12,2), quantity is integer and currency is USD. Tax and
shipping are outside this model. For each customer, sum quantity × unit price,
round that customer's gross × discount percentage to two decimals (half away
from zero), then subtract the rounded discount from gross. A separate query shows
why rounding one aggregate batch discount is a different policy.

`sample_templates` returns one bundled template expecting `customer` and `total`.
Its discovered worker-local path is used directly in SQL, without displaying a
machine-specific path or hard-coding it for readers. A materialized preview uses
the first customer's already rounded net amount; returned paragraphs must include
that customer and amount. The discovery result thus drives a real rendering step.

Our [original companion template](templates/README.md) has six placeholders and
performs no arithmetic. SQL passes customer ID/name, gross, discount percentage,
discount and net as formatted strings. Scalar `docgen_render` produces one BLOB
per context; buffering `docgen_merge` consumes all contexts and emits one BLOB.
Both are materialized before DataFrame capture, so presentation does not repeat
the main rendering operations.

ZIP CRC checks and document-XML inspection compare all eight nonempty paragraphs
per customer against SQL. A multiset comparison checks that the merged file
contains exactly one copy of each block; merge order is not assumed. ZIP headers
and non-NULL outputs are additional checks, not substitutes for content reconciliation.

## One-parameter experiment

```sh
uv run --locked --extra runner vgi-notebooks \
  --parameters '{"DISCOUNT_PCT":15}' --output-dir validation/discount-15
```

Change only **DISCOUNT_PCT**, default **10**, experiment **15**. Accepted values are
whole percentages **0–50**. Predict lower net totals with unchanged source gross,
customer count and document count. Compare the two rounding levels, the amount
chart and verified document text; the bundled preview also uses the new net amount.
Reset to **10** for default publication. Overrides require a separate destination,
and failed execution preserves the successful default and experiment outputs.

Five individual documents and `merged.docx` are written under
`artifacts/generated/discount-10pct/` (or the selected percentage) in the executing
notebook directory. A fresh one-notebook bootstrap may run inside its verified
`.vgi-examples/docgen/` companion directory. These files are local inspection
artifacts, not published downloads. Experiment copies carry the helper/template
and saved text checks; generated DOCX files remain in the execution directory's
artifacts tree. Logs, generated files, review exports and experiment copies are
ignored. Defaults embed SVG MIME and reference committed `charts/` SVGs for GitHub;
experiments retain native SVG without unpublished image links.

## Coverage and limits

[coverage.json](coverage.json) records **3/3** named surfaces: `docgen_render`
(four overloads counted once), `docgen_merge` and `sample_templates`. Complete
released function/table/view exports are retained under [coverage/](coverage/).
Current public registration has the same three names; its release-to-current
source changes are metadata/examples only. This is **three exact released-runtime
examples and zero exact current-runtime examples**, with a separate current-interface
compatibility review. Named-surface coverage does not claim every overload or PDF mode.

This verifies synthetic DOCX content, not real billing rules or Word/LibreOffice
pagination, fonts or complex layouts. No PDF conversion is requested and
LibreOffice is not required. Package sizes measure this template's ZIP packaging,
not runtime performance or a general compression ratio. ZIP metadata and compressed
bytes can change between runs without changing document text.

The scalar invalid-template case returns NULL; a subsequent valid render proves
recovery. Empty merge input produces zero output rows. Eight SQL invariants plus
registry/preview checks, recovery, per-document paragraphs and merged multiplicity
validate the flow. The empty result is not replaced with a fabricated document.

Existing successful [source CI 43565879669](https://github.com/Query-farm/vgi-docgen/actions/runs/43565879669)
is reused for unchanged worker source. No worker rebuild or full source/transport
suite is repeated for this notebook-only change. Upgrade the literal worker release
and shared tool pin deliberately, then rerun defaults/experiment and inspect content
and charts before replacing saved outputs. The community VGI extension is installed
independently of the Python lock.

See the [shared standard](https://github.com/Query-farm/vgi-example-notebooks/blob/v0.3.16/docs/standard.md).
