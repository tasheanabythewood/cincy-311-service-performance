# Cincinnati 311 service performance

**A city service fails every summer, and the fix is not a longer promise.**

An operations analysis of 517,287 Cincinnati 311 service requests, 2023 to 2026.

Bulky-waste collection misses its 14-day commitment in a concentrated,
predictable window every year. In 2024, **84 percent of the service's annual
missed commitments fell in four months**; it runs at 95 to 99 percent the rest
of the year. Demand does not explain it: July 2026 carried 10 percent more
volume than March and lost 21 percentage points.

**Recommendation:** fund seasonal capacity for June to September, and do not
lengthen the commitment. Lengthening it was already tried, during the
off-season, and demonstrated nothing.

Read the [decision memo](reports/recommendation_memo.md) first.

---

## What is here

| File | What it is |
| --- | --- |
| [`reports/recommendation_memo.md`](reports/recommendation_memo.md) | The decision, the trade-offs, the measurement plan, the limits |
| [`reports/metric_dictionary.md`](reports/metric_dictionary.md) | Locked definitions, populations, exclusion rules |
| [`reports/source_definitions.md`](reports/source_definitions.md) | Where the publisher's documentation conflicts with the data |
| [`reports/validation_log__2026-09-18.md`](reports/) | 19 integrity checks with their SQL and results |
| [`reports/analysis_tables__2026-09-18.md`](reports/) | Every analysis query and its output |
| [`reports/charts/`](reports/charts/) | Five figures, with alt text |
| [`CLAUDE.md`](CLAUDE.md) | Locked decisions, known traps, conventions |

## Three findings that only appeared because the data was checked first

**The publisher's own field definition contradicts the data.** The city's data
dictionary states the completion clock starts when work begins. The data starts
it at submission, on 517,214 of 517,214 testable rows, with no exceptions.

**Service descriptions are not a stable identity.** 695 code-and-description
pairs exist across only 524 codes, and 63 percent of requests sit under a code
carrying several concurrent descriptions. One service appears as both
`LITTER, PRIVATE PROPERTY` and `LITTER,  PRIVATE PROPERTY`; the difference is a
single space, and matching on the text dropped 4,598 of 15,824 requests.

**A censoring bias made a failing service look perfect.** Counting a request as
on time the moment it closes, with its deadline still in the future, admits only
the fast closers from a recent cohort. Uncorrected, a 365-day service read
**100 percent on time for 2026**, because nothing created in 2026 is due until
2027. Every trend here is restricted to requests whose committed date had
actually passed.

## How it is built

Python and SQL, DuckDB as the engine, no cloud dependency.

```
python -m src.run_all              # the whole pipeline
python -m src.run_all --no-ingest  # reuse the existing snapshot
python -m src.run_all --from model # resume from a step
```

| Step | Command | Writes |
| --- | --- | --- |
| Inspect a source before pulling it | `python -m src.discover` | console |
| Snapshot plus provenance manifest | `python -m src.ingest` | `data/raw/` |
| 19 integrity checks | `python -m src.validate` | `reports/validation_log__*.md` |
| Apply definitions, reconcile the population | `python -m src.metrics` | console |
| Build and test the star schema | `python -m src.model` | `data/warehouse.duckdb` |
| 15 analysis queries | `python -m src.analysis` | `reports/analysis_tables__*.md` |
| Five figures plus alt text | `python -m src.charts` | `reports/charts/` |
| Aggregates for a dashboard or BI tool | `python -m src.export` | `reports/exports/` |

### Design rules

1. **`data/raw/` is immutable.** Nothing edits a raw file in place. Each pull
   writes a manifest recording the dataset id, the exact filter, the pull
   timestamp, the row count and a SHA-256 hash. Manifests are committed; the
   data files are gitignored and rebuildable from them.
2. **Everything downloads as text.** Types are decided in a later step with the
   rules written down, so "blank" and "missing" stay distinguishable.
3. **Definitions live in one file.** `src/definitions.py` is imported by both the
   model and the analysis, so one definition cannot drift into three.
4. **The model is tested on every build.** Twenty tests covering grain,
   referential integrity, key uniqueness, fan-out, and a reconciliation proving
   the star reproduces the pre-model on-time rate to two decimal places. A
   failure stops the build.
5. **Every record is classified.** All 517,287 fall into exactly one of seven
   outcome buckets, summed and reconciled to the manifest on every run.
6. **Rates are never stored.** The model holds additive counts and divides after
   filtering, so a filtered total cannot become an average of percentages.
7. **The as-of date comes from the snapshot manifest, never the system clock.**
   The same input file must produce the same answer on any day.

## Setup

Windows with Anaconda:

```
conda env create -f environment.yml
conda activate cincy311
python -m src.run_all --no-ingest
```

Other platforms:

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Optional: the Socrata API throttles anonymous requests. Register a free app
token on the portal, then `conda env config vars set SOCRATA_APP_TOKEN=...`.

## Source and limits

City of Cincinnati 311 Non-Emergency Service Requests, dataset `gcej-gmiw`,
published on the [city open data portal](https://data.cincinnati-oh.gov) and
refreshed daily. Snapshot taken 18 September 2026, covering requests created
1 January 2023 to 31 August 2026.

- **311 records reports, not incidents.** Volume reflects what residents choose
  to report and through which channel.
- **Response timeliness cannot be measured.** The field recording when work began
  is blank on 97.8 percent of rows, so only completion timeliness is reported.
- **Closure codes are undefined by the publisher.** Treating them as completed
  service yields a citywide on-time rate of 72.5 percent; under the alternative
  reading it is 61.2 percent. The headline is a range, and the sensitivity test
  is in `src/metrics.py`.
- **Trend reporting covers 13.3 percent of volume.** Only four services held a
  stable commitment across the window.
- **No cost or staffing figure is estimated or assumed anywhere.**

Full list in the [memo](reports/recommendation_memo.md#limitations).

Analysis and views are my own and are not affiliated with or endorsed by the
City of Cincinnati.
