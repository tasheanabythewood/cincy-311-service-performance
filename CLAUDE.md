# Cincinnati 311 service performance

Operations analytics on 517,287 city service requests. Read this before touching
anything: most of what follows was learned by getting it wrong first.

**The decision this project supports:** where the city should add capacity, and
where it should instead reset a service commitment it is not meeting.

---

## Environment

Windows. Anaconda, not venv. Always work from the project root.

```
conda activate cincy311
cd C:\Users\<user>\projects\cincy-311
python -m src.<module>
```

`python src\module.py` fails. The modules use relative imports and need the
package context that `-m` provides.

Rebuild the environment from `environment.yml`, never by installing into `base`.

---

## Pipeline

Each step reads the previous step's output. Run in order.

| Command | Does | Writes |
| --- | --- | --- |
| `python -m src.discover` | Inspect a source before pulling it | console only |
| `python -m src.ingest` | Snapshot plus provenance manifest | `data/raw/` |
| `python -m src.validate` | 19 integrity checks | `reports/validation_log__*.md` |
| `python -m src.metrics` | Apply definitions, reconcile the population | console only |
| `python -m src.model` | Build and test the star schema | `data/warehouse.duckdb` |
| `python -m src.analysis` | 15 analysis queries | `reports/analysis_tables__*.md` |
| `python -m src.charts` | 5 figures plus alt text | `reports/charts/` |
| `python -m src.export` | Aggregates for a dashboard or BI tool | `reports/exports/` |

`python -m src.run_all` runs the lot.

**`src/definitions.py` is the single source of truth.** The model and the analysis
both import it. Change a metric there, nowhere else, and rerun from `model`.

---

## Locked decisions

These were settled with evidence. Do not quietly revisit them; if you think one
is wrong, say so and show the query.

1. **Service identity is `sr_type`, the code. Never `sr_type_desc`.**
   695 code/description pairs across 524 codes. 63 percent of requests sit under
   a code carrying several concurrent descriptions. `LITR-PRV` has two
   descriptions differing by one space, and matching on text silently dropped
   4,598 of 15,824 requests.

2. **The commitment clock starts at submission.**
   The publisher's data dictionary says it starts at first response. The data
   disagrees on 517,214 of 517,214 testable rows. The data wins; the conflict is
   documented in `reports/source_definitions.md`.

3. **Trends use `mature_evaluable_count` and `mature_on_time_count`, never the
   unfiltered versions.**
   A request counted on time the moment it closes, with its deadline still in the
   future, admits only fast closers from recent cohorts. Uncorrected, a 365-day
   service read 100 percent on time for 2026 because nothing created in 2026 is
   due until 2027. Point-in-time rates may use the unfiltered counts.

4. **The as-of date comes from the snapshot manifest, never `CURRENT_DATE`.**
   Otherwise the same input file produces different answers on different days.

5. **Only four services support a trend:** `PTHOLE`, `BLD-RES`, `TLGR-PRV`,
   `LITR-PRV`. Everywhere else the commitment changed mid-window. Demand and
   backlog measures may use all 517,287 records.

6. **Rates are `SUM(numerator) / SUM(denominator)`, always.** No `AVG` of a
   percentage anywhere. No rate stored in the fact table or the exports.

7. **Geography is `neighborhood`, the documented field.**
   `community_council_neighborhood` is undocumented and disagrees on 23.3
   percent of rows. Never mix them.

8. **Duplicates leave service-delivery measures and stay in intake measures.**

---

## Traps this project already hit

- **`NULL` is not `''` in DuckDB.** The CSV reader turns empty fields into NULL,
  so `WHERE x = ''` matches nothing and returns a clean, wrong zero. Use
  `IS NULL` / `IS NOT NULL`.
- **`COUNT(DISTINCT x)` is not dispersion.** Potholes carry 60 distinct
  commitment values and 98.4 percent of them are the same one. Weight by volume
  before calling anything inconsistent.
- **`MAX` is not the typical value.** Use `MODE` for a service standard.
- **Aggregates cannot nest.** `SUM(CASE WHEN x = MODE(x) ...)` is rejected.
  Compute the group summary in a CTE and join it back.
- **DuckDB will not accept a bound parameter in `CREATE VIEW`.** Use the
  `sql_path()` helper in `db.py`.
- **Fix a definition, then sweep for every other place it lived.** Changing the
  stable-service list left three analysis queries still grouping by description.

---

## Charts

`reports/palette.md` has the rules and the measured contrast ratios. The short
version:

- `#1a5442` forest, primary data and links. `#8c2f1f` alert, emphasis only.
- **Alert and forest are 1.06:1 against each other.** Same brightness, hue-only
  separation, identical in greyscale. The alert colour may never be a category
  beside forest, mid grey or black. Pair it with white, off white, light grey or
  sage.
- `#bed4c8` sage is 1.56:1 on white: fills only, never text or a thin line.
- Ordered data gets the sequential ramp. Categorical data gets highlight and
  mute, because only two of the seven palette values carry hue.
- Missing data is left blank, never drawn as zero.
- Every figure needs alt text. Chart titles state the finding, not the variable.

---

## Conventions

- `data/raw/` is immutable. Nothing edits a raw file in place.
- Manifests are committed; the data files they describe are gitignored and
  rebuildable.
- Notebooks explore, scripts produce. Nothing in `notebooks/` is a dependency.
- Every model change must keep all 20 tests in `src/model.py` passing, including
  the one asserting the star reproduces the pre-model on-time rate.
- No cost, staffing or dollar figure is ever estimated or assumed. The city holds
  those inputs.

---

## What is not done

- Step 6, the CSR satisfaction survey link, was scoped and deliberately skipped.
- The mechanism behind the summer failure is unidentified. Volume is
  insufficient to explain it; the rest needs operational data the city holds.
- `reports/charts/02-missed-by-month.png` is generated but kept off the website:
  its title makes a claim about 2024 while 2025 dominates the visual.

---

## Files a reader should see first

| File | What it is |
| --- | --- |
| `reports/recommendation_memo.md` | The decision memo. Start here. |
| `reports/metric_dictionary.md` | Locked definitions, populations, exclusions |
| `reports/source_definitions.md` | Where the publisher's docs conflict with the data |
| `reports/palette.md` | Colour rules and measured contrast |
| `site/cincinnati-311.html` | The public case study |
