# cincy-311-service-performance
The analysis: Python, SQL, reports

[README.md](https://github.com/user-attachments/files/32417262/README.md)
# Cincinnati 311 Service Performance

An operations analytics case study on non-emergency service requests in the
City of Cincinnati.

**Decision this project supports:** which service categories and neighborhoods
are missing the city's service-level commitments, what drives the misses, and
where the city should add capacity versus reset the commitment.

**Status:** step 1 of 10 (data acquisition). No findings yet. Nothing in this
repository should be read as an analytical result.

## Source

| Item | Value |
| --- | --- |
| Publisher | City of Cincinnati, Office of Performance and Data Analytics |
| Dataset | Cincinnati 311 (Non-Emergency) Service Requests |
| Portal | https://data.cincinnati-oh.gov |
| Dataset id | `gcej-gmiw` |
| Refresh | Daily |
| Access | Socrata open data API, no authentication required |

The publisher applies address verification, geocoding, attribute decoding, and
administrative area assignment before publication. Exact terms of use should be
confirmed on the portal before any public release of derived work.

## Setup (Windows, Anaconda Prompt)

Run these from the **Anaconda Prompt**, not Git Bash. Conda activation does not
work in Git Bash without extra configuration. Use Git Bash for git, Anaconda
Prompt for running the project.

```
cd %USERPROFILE%\projects\cincy-311
conda env create -f environment.yml
conda activate cincy311
python -m ipykernel install --user --name cincy311 --display-name "Python (cincy311)"
```

The last line registers the environment as a Jupyter kernel, so notebooks use
the same library versions as the scripts.

Optional. Anonymous API requests are throttled more heavily than
token-authenticated ones. Register a free app token on the portal, then:

```
conda env config vars set SOCRATA_APP_TOKEN=your-token
conda activate cincy311
```

Setting it through conda makes it persist for the environment. A plain
`set SOCRATA_APP_TOKEN=...` only lasts for the current window.

### Other platforms

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Step 1: acquire a reproducible snapshot

**Always run scripts from the project root**, using `-m`. Running
`python src\discover.py` from inside `src\` fails, because the `from . import`
statements need the package context.

```
# 1a. Inspect the dataset before pulling it
python -m src.discover

# 1b. After setting CREATED_DATE_FIELD in src/config.py, pull the snapshot
python -m src.ingest
```

Prefer Jupyter for step 1a? `notebooks/01_discover.ipynb` does the same thing
interactively. Launch with `jupyter lab` from the project root and select the
"Python (cincy311)" kernel.

Outputs land in `data/raw/`:

- `service_requests__<date>.csv.gz` the rows exactly as returned, all values as text
- `service_requests__<date>.manifest.json` dataset id, filter, pull timestamp,
  row count, column list, and a SHA-256 hash of the data file

The data file is gitignored. The manifest is committed. Anyone can reproduce
the data file from the manifest plus `src/ingest.py`.

## Step 2: profile and validate

```
python -m src.validate
```

Runs 17 checks against the snapshot and writes `reports/validation_log__<date>.md`.

This step describes the data and finds its problems. It changes nothing and
interprets nothing. Cleaning rules are decided in step 3, with the evidence
from this log in hand.

## Step 2b: reconcile against the publisher's data dictionary

`reports/source_definitions.md` records where the city's published field
definitions agree with the data, where they conflict, and where the data
contains fields the city has not documented. Step 3 cites it for every metric
definition.

## Step 3: lock the metric definitions

```
python -m src.metrics
```

`src/definitions.py` holds the executable definitions, `reports/metric_dictionary.md`
the prose version for a reader. The script applies them, reconciles every
outcome bucket back to the manifest row count, prints the headline metrics, and
runs a sensitivity test on the one assumption the publisher does not document.

Definitions are locked before any number is produced. Changing one after step 4
means rebuilding the model.

## Step 4: build the dimensional model

```
python -m src.model
```

Builds `data/warehouse.duckdb`: a star schema at one row per service request,
with conformed dimensions for date, service, organization, neighborhood and
status. Eighteen tests run on every build and a failure stops the script.

`dim_date` is a role-playing dimension, joined three times as created, due and
closed. Rates are never stored in the fact table; they are computed from
additive counts so that a filtered total stays correct.

## Step 5: the analysis

```
python -m src.analysis
```

Ten queries against the star schema, written to
`reports/analysis_tables__<date>.md` with their SQL alongside each result.

Produces evidence, not conclusions. The recommendation is step 7 and the charts
are step 8, deliberately separated so the evidence can be checked without
arguing about what it means.

## Step 7: the recommendation

`reports/recommendation_memo.md` states the decision, the recommended action,
what not to act on, how to measure whether it worked, and what the analysis
cannot establish. No cost figures are estimated or assumed.

## Step 8: charts

```
python -m src.charts
```

Writes five figures to `reports/charts/` as PNG and SVG, plus `alt_text.md` and
`alt_text.json`. Static on purpose: a PNG renders everywhere, loads instantly,
and cannot break. Palette is Okabe-Ito, colourblind-safe. Titles state the
finding, not the variable.

## Step 8b: export aggregates

```
python -m src.export
```

Writes `reports/exports/`: one `metrics.json` for a web dashboard and matching
CSVs for Power BI, Tableau or Excel. Pre-aggregated, so a dashboard renders
numbers rather than calculating them, and the site and a BI tool cannot drift
apart. Numerators and denominators are exported, never rates, so filtering
cannot produce a wrong percentage.

## Design rules

1. `data/raw/` is immutable. No step edits a raw file in place.
2. Every value is read as text at download time. Typing happens in step 2 with
   written rules, so that "blank" and "missing" stay distinguishable.
3. Every server-side page request carries an explicit stable sort order.
4. Every number that reaches the website traces back to a named snapshot.

## Layout

```
environment.yml   conda environment definition
src/config.py     all tunable values: dataset ids, window, page size
src/socrata.py    API client: columns, sample, paged fetch, retries
src/discover.py   step 1a, inspect before you pull
src/ingest.py     step 1b, snapshot plus manifest
src/db.py         DuckDB connection, registers the snapshot as a SQL view
src/validate.py   step 2, profiling and validation checks
src/definitions.py step 3, the locked metric definitions (single source of truth)
src/metrics.py    step 3, applies them and reconciles the population
src/model.py      step 4, builds and tests the star schema
src/analysis.py   step 5, the analysis queries
src/charts.py     step 8, static figures and their alt text
src/export.py     step 8b, pre-aggregated metrics for a dashboard or BI tool
data/warehouse.duckdb  the built model (gitignored, rebuildable)
reports/          validation logs, source definitions, metric dictionary (committed)
notebooks/        exploration only, never a pipeline dependency
data/raw/         immutable snapshots (gitignored) and manifests (committed)
```

**Notebooks explore, scripts produce.** A notebook can be run out of order and
still work in your session while failing for everyone else. Anything a later
step depends on lives in `src/`.

