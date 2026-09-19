"""
Step 4. Build the star schema.

WHAT A STAR SCHEMA IS: one fact table holding the events you measure, surrounded
by dimension tables holding the attributes you slice by. Every fact row carries
a small integer key pointing at each dimension.

WHY BOTHER, when the flat `analysis` view already works: three reasons that
matter to a hiring manager.

  1. One definition of a department, a service, a neighbourhood. When somebody
     asks "how many departments are there?", there is a table to count.
  2. Filters behave predictably. Slicing by month, service and department is a
     join, not a pile of string comparisons against a wide table.
  3. It is the shape BI tools expect. Power BI, Tableau and Looker all assume
     this model, and building one is the core skill of a BI analyst role.

GRAIN, DECLARED BEFORE ANYTHING ELSE: one row per service request, identified
by sr_number. Check C02 confirmed sr_number is unique across all 517,287 rows,
and the tests at the end re-confirm it in the fact table. Every measure in the
model is therefore a count of requests or an attribute of one request. If a
future requirement needs something finer, such as one row per status change,
that is a second fact table, not a change to this one.

Usage:
    python -m src.model
"""

from __future__ import annotations

import json

from . import config, db, definitions

# The unknown member. Every dimension gets a row with key -1 so that a fact row
# with a missing or unmatched attribute still joins.
#
# WHY THIS EXISTS: the classic star-schema bug is an INNER JOIN silently
# dropping fact rows whose dimension value is NULL. The totals shrink, nobody
# notices, and the dashboard is quietly wrong. Every join below is a LEFT JOIN
# that falls back to -1, and a test asserts no fact row carries a key absent
# from its dimension.
UNKNOWN_KEY = -1


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

DIM_DATE = """
CREATE OR REPLACE TABLE dim_date AS
SELECT
    -1                AS date_key,
    CAST(NULL AS DATE) AS full_date,
    CAST(NULL AS INTEGER) AS year,
    CAST(NULL AS INTEGER) AS quarter,
    CAST(NULL AS INTEGER) AS month_number,
    '(unknown)'       AS month_name,
    '(unknown)'       AS year_month,
    CAST(NULL AS INTEGER) AS day_of_month,
    '(unknown)'       AS day_name,
    FALSE             AS is_weekend
UNION ALL
SELECT
    CAST(strftime(d, '%Y%m%d') AS INTEGER) AS date_key,
    d                                      AS full_date,
    year(d)                                AS year,
    quarter(d)                             AS quarter,
    month(d)                               AS month_number,
    strftime(d, '%B')                      AS month_name,
    strftime(d, '%Y-%m')                   AS year_month,
    day(d)                                 AS day_of_month,
    strftime(d, '%A')                      AS day_name,
    (dayofweek(d) IN (0, 6))               AS is_weekend
FROM (
    -- Wide enough to cover every date the model can reference. Creation dates
    -- stop at 2026-08-31, but a 365-day commitment on a late-2026 request puts
    -- due dates well into 2027, and the 970-day outliers reach further still.
    -- A date dimension that is too short produces unknown keys, not an error,
    -- which is exactly the kind of silent gap the tests below look for.
    SELECT CAST(UNNEST(generate_series(
        DATE '2022-01-01', DATE '2031-12-31', INTERVAL 1 DAY
    )) AS DATE) AS d
)
"""

DIM_SERVICE = """
CREATE OR REPLACE TABLE dim_service AS
WITH base AS (
    SELECT
        sr_type,
        sr_type_desc,
        MODE(service_label) AS service_label,
        MODE(committed_days) AS modal_committed_days,
        MIN(committed_days)  AS min_committed_days,
        MAX(committed_days)  AS max_committed_days,
        COUNT(*)             AS request_count,
        BOOL_OR(stable_commitment_service) AS stable_commitment,
        BOOL_OR(bulk_collection_family)    AS bulk_collection_family
    FROM analysis
    GROUP BY sr_type, sr_type_desc
)
SELECT
    -1 AS service_key, '(unknown)' AS sr_type, '(unknown)' AS sr_type_desc,
    '(unknown)' AS service_label,
    CAST(NULL AS INTEGER) AS modal_committed_days,
    CAST(NULL AS INTEGER) AS min_committed_days,
    CAST(NULL AS INTEGER) AS max_committed_days,
    0 AS request_count, FALSE AS stable_commitment, FALSE AS bulk_collection_family
UNION ALL
SELECT
    CAST(ROW_NUMBER() OVER (ORDER BY sr_type_desc, sr_type) AS INTEGER) AS service_key,
    sr_type, sr_type_desc, service_label, modal_committed_days, min_committed_days,
    max_committed_days, request_count, stable_commitment, bulk_collection_family
FROM base
"""

DIM_ORGANIZATION = """
CREATE OR REPLACE TABLE dim_organization AS
WITH base AS (
    -- Department and division are a hierarchy, but not a clean one: a division
    -- can appear under more than one department code in this data. Grouping on
    -- the full combination keeps the model honest rather than forcing a tidy
    -- parent-child tree the source does not support.
    SELECT
        dept_name,
        group_title,
        COUNT(*) AS request_count
    FROM analysis
    GROUP BY dept_name, group_title
)
SELECT
    -1 AS org_key, '(unknown)' AS dept_name, '(unknown)' AS group_title, 0 AS request_count
UNION ALL
SELECT
    CAST(ROW_NUMBER() OVER (ORDER BY dept_name, group_title) AS INTEGER) AS org_key,
    dept_name, group_title, request_count
FROM base
"""

DIM_NEIGHBORHOOD = """
CREATE OR REPLACE TABLE dim_neighborhood AS
WITH base AS (
    -- Only the documented field. community_council_neighborhood disagrees on
    -- 23.3 percent of rows and the publisher does not define it, so it is not
    -- modelled. See reports/source_definitions.md section 3.
    SELECT neighborhood, COUNT(*) AS request_count
    FROM analysis
    GROUP BY neighborhood
)
SELECT -1 AS neighborhood_key, '(unknown)' AS neighborhood, 0 AS request_count
UNION ALL
SELECT
    CAST(ROW_NUMBER() OVER (ORDER BY neighborhood) AS INTEGER) AS neighborhood_key,
    neighborhood, request_count
FROM base
"""


def dim_status_sql() -> str:
    codes = ", ".join(f"'{c}'" for c in definitions.UNDEFINED_CLOSURE_CODES)
    return f"""
CREATE OR REPLACE TABLE dim_status AS
WITH base AS (
    SELECT
        sr_status,
        COALESCE(sr_status_flag, '(not stated)') AS sr_status_flag,
        (sr_status = '{definitions.DUPLICATE_CODE}') AS is_duplicate,
        -- Flagged so the sensitivity test can be reproduced from the model,
        -- and so a dashboard user can see which codes the publisher never
        -- defined rather than having to take the headline rate on trust.
        (sr_status IN ({codes}))                     AS is_undefined_code,
        COUNT(*) AS request_count
    FROM analysis
    GROUP BY sr_status, sr_status_flag
)
SELECT
    -1 AS status_key, '(unknown)' AS sr_status, '(unknown)' AS sr_status_flag,
    FALSE AS is_duplicate, FALSE AS is_undefined_code, 0 AS request_count
UNION ALL
SELECT
    CAST(ROW_NUMBER() OVER (ORDER BY sr_status, sr_status_flag) AS INTEGER) AS status_key,
    sr_status, sr_status_flag, is_duplicate, is_undefined_code, request_count
FROM base
"""


# ---------------------------------------------------------------------------
# Fact
# ---------------------------------------------------------------------------

FACT = f"""
CREATE OR REPLACE TABLE fact_service_request AS
SELECT
    -- Degenerate dimensions: identifiers and low-cardinality attributes that
    -- have no attributes of their own and no hierarchy. A dimension table for
    -- three priority values would add a join and explain nothing.
    a.sr_number,
    a.priority,
    a.method_received,
    a.zipcode,

    -- Foreign keys. dim_date is a role-playing dimension, joined three times
    -- under three different roles. One calendar, three questions: when was it
    -- submitted, when was it due, when was it closed.
    COALESCE(dc.date_key, {UNKNOWN_KEY}) AS created_date_key,
    COALESCE(dd.date_key, {UNKNOWN_KEY}) AS due_date_key,
    COALESCE(dx.date_key, {UNKNOWN_KEY}) AS closed_date_key,
    COALESCE(s.service_key,      {UNKNOWN_KEY}) AS service_key,
    COALESCE(o.org_key,          {UNKNOWN_KEY}) AS org_key,
    COALESCE(n.neighborhood_key, {UNKNOWN_KEY}) AS neighborhood_key,
    COALESCE(st.status_key,      {UNKNOWN_KEY}) AS status_key,

    -- Non-additive attributes of the request. Averaging days_to_close across
    -- services is meaningless when commitments run from 1 day to 365, which is
    -- why the metric dictionary specifies a median and why these are stored
    -- per request rather than pre-aggregated.
    a.committed_days,
    a.days_to_close,
    a.days_past_due,
    a.days_overdue_open,
    a.deadline_revised,
    a.is_mature,
    a.outcome,

    -- Additive measures. Every rate in the model is built by summing these and
    -- dividing, never by averaging a percentage.
    --
    -- WHY THAT RULE MATTERS: a service with 20 requests at 50 percent on time
    -- and one with 20,000 at 90 percent do not average to 70 percent. Averaging
    -- percentages gives every group equal weight regardless of size. Summing
    -- the numerator and denominator separately gives the real figure.
    1                                                             AS request_count,
    CASE WHEN a.outcome = 'on time' THEN 1 ELSE 0 END             AS on_time_count,
    CASE WHEN a.outcome = 'late' THEN 1 ELSE 0 END                AS closed_late_count,
    CASE WHEN a.outcome = 'open, overdue' THEN 1 ELSE 0 END       AS open_overdue_count,
    CASE WHEN a.outcome IN ('on time', 'late', 'open, overdue')
         THEN 1 ELSE 0 END                                        AS evaluable_count,
    CASE WHEN a.outcome = 'excluded: duplicate request'
         THEN 1 ELSE 0 END                                        AS duplicate_count,

    -- Maturity-filtered counterparts. Use these for any TREND; the unfiltered
    -- ones remain correct for a point-in-time rate. Separating them means a
    -- query cannot accidentally mix a censored cohort into a time series.
    CASE WHEN a.is_mature AND a.outcome IN ('on time', 'late', 'open, overdue')
         THEN 1 ELSE 0 END                                        AS mature_evaluable_count,
    CASE WHEN a.is_mature AND a.outcome = 'on time'
         THEN 1 ELSE 0 END                                        AS mature_on_time_count
FROM analysis a
-- LEFT JOIN throughout, never INNER. An INNER JOIN here would drop any request
-- whose attribute is missing, shrinking the totals without raising an error.
LEFT JOIN dim_date         dc ON dc.full_date     = a.created_date
LEFT JOIN dim_date         dd ON dd.full_date     = a.due_date
LEFT JOIN dim_date         dx ON dx.full_date     = a.closed_date
LEFT JOIN dim_service      s  ON s.sr_type        IS NOT DISTINCT FROM a.sr_type
                             AND s.sr_type_desc   IS NOT DISTINCT FROM a.sr_type_desc
LEFT JOIN dim_organization o  ON o.dept_name      = a.dept_name
                             AND o.group_title    = a.group_title
LEFT JOIN dim_neighborhood n  ON n.neighborhood   = a.neighborhood
LEFT JOIN dim_status       st ON st.sr_status     IS NOT DISTINCT FROM a.sr_status
                             AND st.sr_status_flag = COALESCE(a.sr_status_flag, '(not stated)')
"""


# ---------------------------------------------------------------------------
# Tests
#
# Each returns (name, passed, detail). A model that has not been tested is a
# guess. These run every build, and a failure stops the script.
# ---------------------------------------------------------------------------

def run_tests(con, expected_rows: int) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, sql: str, expect, formatter=str) -> None:
        got = con.execute(sql).fetchone()[0]
        results.append((name, got == expect, f"expected {formatter(expect)}, got {formatter(got)}"))

    # T1. Row count survived the build.
    check("fact row count matches the snapshot",
          "SELECT COUNT(*) FROM fact_service_request", expected_rows, lambda v: f"{v:,}")

    # T2. Grain holds: one row per request.
    check("sr_number is unique in the fact table",
          "SELECT COUNT(*) - COUNT(DISTINCT sr_number) FROM fact_service_request", 0)

    # T3. No NULL foreign keys. COALESCE should have caught every one.
    check("no NULL foreign keys",
          """SELECT COUNT(*) FROM fact_service_request
             WHERE created_date_key IS NULL OR due_date_key IS NULL
                OR closed_date_key IS NULL OR service_key IS NULL
                OR org_key IS NULL OR neighborhood_key IS NULL
                OR status_key IS NULL""", 0)

    # T4. Referential integrity: every key present in its dimension.
    for fk, dim, pk in [
        ("created_date_key", "dim_date", "date_key"),
        ("due_date_key", "dim_date", "date_key"),
        ("closed_date_key", "dim_date", "date_key"),
        ("service_key", "dim_service", "service_key"),
        ("org_key", "dim_organization", "org_key"),
        ("neighborhood_key", "dim_neighborhood", "neighborhood_key"),
        ("status_key", "dim_status", "status_key"),
    ]:
        check(f"no orphan {fk}",
              f"""SELECT COUNT(*) FROM fact_service_request f
                  LEFT JOIN {dim} d ON d.{pk} = f.{fk}
                  WHERE d.{pk} IS NULL""", 0)

    # T5. Dimension keys are unique. A duplicate key fans out the fact table on
    # join and inflates every total, which is the single most damaging star
    # schema defect because the numbers look plausible.
    for dim, pk in [("dim_date", "date_key"), ("dim_service", "service_key"),
                    ("dim_organization", "org_key"),
                    ("dim_neighborhood", "neighborhood_key"),
                    ("dim_status", "status_key")]:
        check(f"{dim}.{pk} is unique",
              f"SELECT COUNT(*) - COUNT(DISTINCT {pk}) FROM {dim}", 0)

    # T6. Joining every dimension does not change the row count. This is the
    # direct test for accidental fan-out.
    check("full star join preserves the row count",
          """SELECT COUNT(*) FROM fact_service_request f
             JOIN dim_date         dc ON dc.date_key         = f.created_date_key
             JOIN dim_date         dd ON dd.date_key         = f.due_date_key
             JOIN dim_date         dx ON dx.date_key         = f.closed_date_key
             JOIN dim_service      s  ON s.service_key       = f.service_key
             JOIN dim_organization o  ON o.org_key           = f.org_key
             JOIN dim_neighborhood n  ON n.neighborhood_key  = f.neighborhood_key
             JOIN dim_status       st ON st.status_key       = f.status_key""",
          expected_rows, lambda v: f"{v:,}")

    # T7. Unknown members are not being used where a real value existed. Only
    # closed_date_key should carry -1, for requests that are still open.
    check("only closed_date_key uses the unknown member",
          """SELECT COUNT(*) FROM fact_service_request
             WHERE created_date_key = -1 OR service_key = -1
                OR org_key = -1 OR neighborhood_key = -1 OR status_key = -1""", 0)

    # T8. The model reproduces step 3 exactly. If the star schema changed a
    # number, the star schema is wrong, not step 3.
    star = con.execute(
        """SELECT ROUND(100.0 * SUM(on_time_count) / NULLIF(SUM(evaluable_count), 0), 2)
           FROM fact_service_request"""
    ).fetchone()[0]
    flat = con.execute(
        """SELECT ROUND(100.0 * SUM(CASE WHEN outcome = 'on time' THEN 1 ELSE 0 END)
           / NULLIF(SUM(CASE WHEN outcome IN ('on time','late','open, overdue')
                             THEN 1 ELSE 0 END), 0), 2) FROM analysis"""
    ).fetchone()[0]
    results.append(("on-time rate matches the step 3 view",
                    star == flat, f"star {star}, flat {flat}"))

    # T9. Maturity is a strict subset of evaluable. If a mature row is not
    # evaluable, the two definitions have drifted apart.
    check("mature_evaluable is a subset of evaluable",
          """SELECT COUNT(*) FROM fact_service_request
             WHERE mature_evaluable_count = 1 AND evaluable_count = 0""", 0)

    # T10. Nothing can be late or overdue while immature: both require the
    # committed date to have passed.
    check("no late or overdue request is marked immature",
          """SELECT COUNT(*) FROM fact_service_request
             WHERE NOT is_mature
               AND outcome IN ('late', 'open, overdue')""", 0)

    return results


def run() -> None:
    source, snapshot_date = db.latest_snapshot()
    manifest = json.loads(
        (source.parent / source.name.replace(".csv.gz", ".manifest.json")).read_text()
    )
    expected_rows = int(manifest["row_count"])

    print(f"Snapshot  : {source.name}")
    print(f"Warehouse : {config.WAREHOUSE}")
    print(f"Grain     : one row per service request (sr_number)")
    print(f"Rows      : {expected_rows:,}\n")

    con = db.connect_warehouse(source)
    con.execute(definitions.analysis_view_sql(snapshot_date))

    for label, sql in [
        ("dim_date", DIM_DATE),
        ("dim_service", DIM_SERVICE),
        ("dim_organization", DIM_ORGANIZATION),
        ("dim_neighborhood", DIM_NEIGHBORHOOD),
        ("dim_status", dim_status_sql()),
        ("fact_service_request", FACT),
    ]:
        con.execute(sql)
        n = con.execute(f"SELECT COUNT(*) FROM {label}").fetchone()[0]
        print(f"  built {label:<24}{n:>10,} rows")

    print("\n" + "=" * 72)
    print("MODEL TESTS")
    print("=" * 72)
    results = run_tests(con, expected_rows)
    failed = 0
    for name, passed, detail in results:
        mark = "PASS" if passed else "FAIL"
        if not passed:
            failed += 1
        print(f"  [{mark}] {name:<48}{detail}")

    print(f"\n  {len(results) - failed} passed, {failed} failed")
    con.close()

    if failed:
        raise SystemExit("Model tests failed. Do not build anything on top of this.")
    print(f"\n  Warehouse written to {config.WAREHOUSE}")


if __name__ == "__main__":
    run()
