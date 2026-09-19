"""
Step 3 verification. Apply the locked definitions and prove they hold together.

This does four things, in order:

  1. Builds the `analysis` view from the definitions.
  2. Reconciles every outcome bucket back to the manifest row count. If they do
     not sum exactly, a request has fallen through the CASE expression and the
     definitions are wrong.
  3. Prints each headline metric once, for the whole population and for the
     four stable-commitment services.
  4. Runs a sensitivity test on the one assumption the publisher does not
     document: that the undefined closure codes represent completed service.

WHY STEP 3 ENDS WITH A RECONCILIATION: a metric definition is a claim that
every record has a defined treatment. The only way to know the claim is true is
to add the buckets up. This is the check that separates a metric dictionary
from a wish list.

Usage:
    python -m src.metrics
"""

from __future__ import annotations

import json

from . import config, db, definitions


def build(con, as_of_date: str) -> None:
    con.execute(definitions.analysis_view_sql(as_of_date))


def reconcile(con, expected_rows: int) -> bool:
    print("\n" + "=" * 72)
    print("POPULATION RECONCILIATION")
    print("=" * 72)

    frame = con.execute(
        """
        SELECT
            outcome,
            COUNT(*) AS requests,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
        FROM analysis
        GROUP BY outcome
        ORDER BY requests DESC
        """
    ).fetchdf()
    print(frame.to_string(index=False))

    total = int(frame["requests"].sum())
    print(f"\n  bucket total   : {total:,}")
    print(f"  manifest rows  : {expected_rows:,}")
    matched = total == expected_rows
    print(f"  reconciles     : {matched}")
    if not matched:
        print("\n  FAILED. Some requests are unaccounted for. Do not proceed to step 4.")
    return matched


def headline(con) -> None:
    select = ",\n            ".join(
        f"{expr} AS {name}" for name, expr, _ in definitions.METRICS
    )

    for label, where in [
        ("ALL SERVICES", "1 = 1"),
        ("STABLE-COMMITMENT SERVICES ONLY", "stable_commitment_service"),
    ]:
        print("\n" + "=" * 72)
        print(f"HEADLINE METRICS: {label}")
        print("=" * 72)
        frame = con.execute(
            f"SELECT\n            {select}\n        FROM analysis WHERE {where}"
        ).fetchdf()
        for name, _, description in definitions.METRICS:
            value = frame[name].iloc[0]
            shown = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
            print(f"  {name:<28}{shown:>14}   {description.split('.')[0]}")


def by_service(con) -> None:
    print("\n" + "=" * 72)
    print("STABLE-COMMITMENT SERVICES, BROKEN OUT")
    print("=" * 72)
    frame = con.execute(
        """
        -- Two passes, not one. SQL evaluates every aggregate in a SELECT over
        -- the same group in a single pass, so the result of one aggregate is
        -- not available inside another: SUM(CASE WHEN x = MODE(x) ...) is
        -- rejected as a nested aggregate. The CTE computes the modal
        -- commitment first; the outer query then treats it as an ordinary
        -- grouped column and can compare individual rows against it.
        WITH modal AS (
            SELECT
                sr_type_desc,
                MODE(committed_days) AS modal_days
            FROM analysis
            WHERE stable_commitment_service
              AND committed_days IS NOT NULL
            GROUP BY sr_type_desc
        )
        SELECT
            a.sr_type_desc,
            -- MODE, not MAX. MAX reports the longest commitment ever recorded,
            -- which on potholes is a 313-day outlier attached to well under one
            -- percent of requests. The modal value is the actual service
            -- standard, and pct_at_modal shows how standard it really is.
            m.modal_days,
            ROUND(100.0 * SUM(CASE WHEN a.committed_days = m.modal_days
                                   THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(a.committed_days), 0), 1)               AS pct_at_modal,
            COUNT(*)                                                     AS intake,
            SUM(CASE WHEN a.outcome IN ('on time','late','open, overdue')
                     THEN 1 ELSE 0 END)                                  AS evaluable,
            ROUND(100.0 * SUM(CASE WHEN a.outcome = 'on time' THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN a.outcome IN ('on time','late','open, overdue')
                                    THEN 1 ELSE 0 END), 0), 1)           AS on_time_pct,
            -- Misses split by kind. A request closed late and a request never
            -- closed at all are both misses, but they point at different
            -- problems and different fixes.
            SUM(CASE WHEN a.outcome = 'late' THEN 1 ELSE 0 END)          AS closed_late,
            SUM(CASE WHEN a.outcome = 'open, overdue' THEN 1 ELSE 0 END) AS open_overdue,
            MEDIAN(CASE WHEN a.outcome IN ('on time','late')
                        THEN a.days_to_close END)                        AS median_days_to_close,
            MEDIAN(CASE WHEN a.outcome = 'open, overdue'
                        THEN a.days_overdue_open END)                    AS median_days_overdue
        FROM analysis a
        JOIN modal m ON a.sr_type_desc = m.sr_type_desc
        WHERE a.stable_commitment_service
        GROUP BY a.sr_type_desc, m.modal_days
        ORDER BY intake DESC
        """
    ).fetchdf()
    print(frame.to_string(index=False))


def sensitivity(con) -> None:
    """
    How much does the on-time rate depend on the one undocumented assumption?

    The primary metric treats every closure code as a completed service. The
    publisher defines none of them. If the undefined codes in fact mean the
    city did no work, the true rate would be lower. This shows by how much,
    so the case study can state the range rather than a single number the
    evidence does not support.
    """
    codes = ", ".join(f"'{c}'" for c in definitions.UNDEFINED_CLOSURE_CODES)
    print("\n" + "=" * 72)
    print("SENSITIVITY: undefined closure codes")
    print("=" * 72)
    frame = con.execute(
        f"""
        SELECT
            'A. all closures count as service'                  AS assumption,
            ROUND(100.0 * SUM(CASE WHEN outcome = 'on time' THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN outcome IN ('on time','late','open, overdue')
                                    THEN 1 ELSE 0 END), 0), 1)  AS on_time_pct,
            SUM(CASE WHEN outcome IN ('on time','late','open, overdue')
                     THEN 1 ELSE 0 END)                         AS evaluable
        FROM analysis
        UNION ALL
        SELECT
            'B. undefined closure codes excluded',
            ROUND(100.0 * SUM(CASE WHEN outcome = 'on time' THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN outcome IN ('on time','late','open, overdue')
                                    THEN 1 ELSE 0 END), 0), 1),
            SUM(CASE WHEN outcome IN ('on time','late','open, overdue')
                     THEN 1 ELSE 0 END)
        FROM analysis
        WHERE sr_status NOT IN ({codes})
        UNION ALL
        SELECT
            'C. undefined closure codes count as late',
            ROUND(100.0 * SUM(CASE WHEN outcome = 'on time'
                                    AND sr_status NOT IN ({codes})
                                   THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN outcome IN ('on time','late','open, overdue')
                                    THEN 1 ELSE 0 END), 0), 1),
            SUM(CASE WHEN outcome IN ('on time','late','open, overdue')
                     THEN 1 ELSE 0 END)
        FROM analysis
        """
    ).fetchdf()
    print(frame.to_string(index=False))
    print(
        "\n  If A and C are far apart, the headline number rests on an assumption\n"
        "  the publisher never documented, and the case study must say so."
    )


def run() -> None:
    source, snapshot_date = db.latest_snapshot()
    manifest_path = source.parent / source.name.replace(".csv.gz", ".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    expected_rows = int(manifest["row_count"])

    print(f"Snapshot  : {source.name}")
    print(f"As-of date: {snapshot_date}  (from the manifest, not today's date)")
    print(f"Rows      : {expected_rows:,}")

    con = db.connect(source)
    build(con, snapshot_date)

    ok = reconcile(con, expected_rows)
    headline(con)
    by_service(con)
    sensitivity(con)

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 72)
    print("Definitions applied from src/definitions.py")
    print("Prose version in reports/metric_dictionary.md")
    if not ok:
        raise SystemExit("Reconciliation failed. Fix the definitions before step 4.")


if __name__ == "__main__":
    run()
