"""
Step 2. Profile and validate the raw snapshot before any analysis.

WHAT THIS STEP IS FOR: finding out what is actually in the file, and finding
the problems now rather than after you have built a dashboard on top of them.
Every check here answers a question an interviewer can reasonably ask, and the
output file is the evidence that you asked it yourself.

WHAT THIS STEP DELIBERATELY DOES NOT DO: clean anything, change anything, or
interpret anything as a finding about city performance. Profiling describes
the data. Step 3 defines metrics. Step 5 produces findings. Mixing those up is
how you end up reporting a data bug as an operational insight.

Each check is independent. If one fails, the rest still run and the failure is
recorded in the log with its SQL, so it can be diagnosed rather than silently
skipped.

Usage:
    python -m src.validate
"""

from __future__ import annotations

import datetime as dt
import json
import textwrap

from . import config, db

# ---------------------------------------------------------------------------
# Check definitions
#
# Each check is (id, title, why_it_matters, sql). Keeping them as data rather
# than as a long procedural script means the log and the console output stay
# in sync automatically, and adding a check is a three-line edit.
# ---------------------------------------------------------------------------

CHECKS: list[tuple[str, str, str, str]] = [
    (
        "C01",
        "Row count",
        "Must match the manifest and the count the API reported. A mismatch means "
        "the download was truncated or the paging duplicated rows.",
        "SELECT COUNT(*) AS row_count FROM raw",
    ),
    (
        "C02",
        "Grain: is sr_number unique?",
        "The whole model assumes one row per service request. If it is not, every "
        "count downstream is inflated and every average is wrong.",
        """
        SELECT
            COUNT(*)                                AS total_rows,
            COUNT(DISTINCT sr_number)               AS distinct_sr_numbers,
            COUNT(*) - COUNT(DISTINCT sr_number)    AS excess_rows
        FROM raw
        """,
    ),
    (
        "C03",
        "Duplicate sr_number examples",
        "If C02 shows excess rows, these are the ones to inspect. Duplicates are "
        "sometimes genuine revisions rather than errors, and that changes the fix.",
        """
        SELECT sr_number, COUNT(*) AS occurrences
        FROM raw
        GROUP BY sr_number
        HAVING COUNT(*) > 1
        ORDER BY occurrences DESC, sr_number
        LIMIT 10
        """,
    ),
    (
        "C04",
        "Date coverage",
        "Confirms the filter did what it claimed. Values outside the requested "
        "window mean the server-side filter did not behave as expected.",
        """
        SELECT
            MIN(substr(date_created, 1, 10)) AS earliest_created,
            MAX(substr(date_created, 1, 10)) AS latest_created,
            SUM(CASE WHEN date_created IS NULL OR date_created = '' THEN 1 ELSE 0 END)
                AS blank_created
        FROM raw
        """,
    ),
    (
        "C05",
        "Monthly volume",
        "Reveals gaps, partial months, and system changes. A month at half the "
        "usual volume is almost always a collection problem, not a real drop in "
        "demand, and analysing it as demand would be a serious error.",
        """
        SELECT
            substr(date_created, 1, 7) AS month,
            COUNT(*)                   AS requests
        FROM raw
        WHERE date_created IS NOT NULL
        GROUP BY month
        ORDER BY month
        """,
    ),
    (
        "C06",
        "Status distribution",
        "Establishes how open and closed are represented, and whether sr_status_flag "
        "is a clean binary that can be trusted for the backlog definition.",
        """
        SELECT
            sr_status_flag,
            sr_status,
            COUNT(*) AS requests
        FROM raw
        GROUP BY sr_status_flag, sr_status
        ORDER BY requests DESC
        LIMIT 30
        """,
    ),
    (
        "C07",
        "SLA arithmetic: does date_created + planned_completion_days = planned_end_date?",
        "This held on all five sample rows. If it holds across the full file, the "
        "completion deadline is a reliable published commitment and becomes the "
        "backbone of the on-time metric. If it does not, the exceptions need a rule.",
        """
        SELECT
            COUNT(*) AS rows_testable,
            SUM(CASE
                    WHEN TRY_CAST(substr(date_created, 1, 10) AS DATE)
                         + CAST(TRY_CAST(planned_completion_days AS DOUBLE) AS INTEGER)
                         = TRY_CAST(substr(planned_end_date, 1, 10) AS DATE)
                    THEN 1 ELSE 0
                END) AS arithmetic_matches
        FROM raw
        WHERE planned_completion_days IS NOT NULL
          AND planned_end_date IS NOT NULL
          AND date_created IS NOT NULL
        """,
    ),
    (
        "C08",
        "Deadline revisions",
        "If the city revises deadlines often, measuring on-time against the revised "
        "date flatters performance. This decides whether the original deadline has "
        "to be the basis of the metric, and whether revision rate is itself a finding.",
        """
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN date_revised_completion IS NOT NULL THEN 1 ELSE 0 END)
                AS revised_rows,
            ROUND(
                100.0 * SUM(CASE WHEN date_revised_completion IS NOT NULL THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0), 2) AS revised_pct
        FROM raw
        """,
    ),
    (
        "C09",
        "Neighborhood columns: how often do they disagree?",
        "Two geography columns exist and at least one sample row disagreed. Since "
        "the analysis compares neighborhoods, the wrong choice produces geography "
        "that does not reconcile against anything the city publishes.",
        """
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN neighborhood IS NULL THEN 1 ELSE 0 END)
                AS neighborhood_blank,
            SUM(CASE WHEN community_council_neighborhood IS NULL THEN 1 ELSE 0 END)
                AS council_blank,
            SUM(CASE
                    WHEN neighborhood IS NOT NULL
                     AND community_council_neighborhood IS NOT NULL
                     AND upper(trim(neighborhood))
                         <> upper(trim(community_council_neighborhood))
                    THEN 1 ELSE 0
                END) AS disagreements
        FROM raw
        """,
    ),
    (
        "C10",
        "Impossible dates: closed before created",
        "A record closed before it was created is a data error. The count tells you "
        "whether to exclude a handful of rows or investigate a systemic problem.",
        """
        SELECT
            SUM(CASE
                    WHEN date_closed IS NOT NULL AND date_created IS NOT NULL
                     AND TRY_CAST(substr(date_closed, 1, 10) AS DATE)
                         < TRY_CAST(substr(date_created, 1, 10) AS DATE)
                    THEN 1 ELSE 0
                END) AS closed_before_created,
            SUM(CASE
                    WHEN date_closed IS NOT NULL AND date_created IS NOT NULL
                     AND TRY_CAST(substr(date_closed, 1, 10) AS DATE)
                         = TRY_CAST(substr(date_created, 1, 10) AS DATE)
                    THEN 1 ELSE 0
                END) AS closed_same_day
        FROM raw
        """,
    ),
    (
        "C11",
        "time_received format consistency",
        "Time of day lives in a separate text column. Before reassembling it with "
        "the date in step 3, confirm every value follows one format. A single "
        "24-hour value mixed into 12-hour values would shift results by 12 hours.",
        """
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN time_received IS NULL THEN 1 ELSE 0 END) AS blank_time,
            SUM(CASE
                    WHEN time_received IS NOT NULL
                     AND NOT regexp_matches(time_received, '^[0-9]{1,2}:[0-9]{2} (AM|PM)$')
                    THEN 1 ELSE 0
                END) AS unexpected_format
        FROM raw
        """,
    ),
    (
        "C12",
        "time_received unexpected-format examples",
        "Shows the actual offending values, if C11 found any, so the parsing rule "
        "can handle them explicitly rather than by guesswork.",
        """
        SELECT time_received, COUNT(*) AS occurrences
        FROM raw
        WHERE time_received IS NOT NULL
          AND NOT regexp_matches(time_received, '^[0-9]{1,2}:[0-9]{2} (AM|PM)$')
        GROUP BY time_received
        ORDER BY occurrences DESC
        LIMIT 15
        """,
    ),
    (
        "C13",
        "Censoring: open requests and overdue open requests",
        "Open requests have no closure date, so they cannot be included in an "
        "average time-to-close without biasing it downward. Requests still within "
        "their deadline are not yet late and must not be counted as misses.",
        """
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN sr_status_flag = 'OPEN' THEN 1 ELSE 0 END) AS open_rows,
            SUM(CASE WHEN date_closed IS NULL THEN 1 ELSE 0 END) AS no_close_date,
            SUM(CASE
                    WHEN date_closed IS NULL
                     AND TRY_CAST(substr(planned_end_date, 1, 10) AS DATE) < CURRENT_DATE
                    THEN 1 ELSE 0
                END) AS open_and_past_deadline,
            SUM(CASE
                    WHEN date_closed IS NULL
                     AND TRY_CAST(substr(planned_end_date, 1, 10) AS DATE) >= CURRENT_DATE
                    THEN 1 ELSE 0
                END) AS open_and_not_yet_due
        FROM raw
        """,
    ),
    (
        "C14",
        "Request type concentration",
        "Shows whether a handful of types dominate volume. If they do, an overall "
        "on-time rate is really a weighted average of a few services, and the "
        "analysis has to segment rather than report one headline number.",
        """
        SELECT
            sr_type_desc,
            COUNT(*)                                      AS requests,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
        FROM raw
        GROUP BY sr_type_desc
        ORDER BY requests DESC
        LIMIT 20
        """,
    ),
    (
        "C15",
        "Committed completion days by request type",
        "The city promises 7 days for some services and 72 for others. This is the "
        "evidence that an unsegmented on-time rate would be misleading, and it "
        "shows whether a type's commitment has changed over time.",
        """
        SELECT
            sr_type_desc,
            COUNT(*)                                                       AS requests,
            COUNT(DISTINCT planned_completion_days)                        AS distinct_commitments,
            MIN(TRY_CAST(planned_completion_days AS DOUBLE))               AS min_days,
            MAX(TRY_CAST(planned_completion_days AS DOUBLE))               AS max_days
        FROM raw
        WHERE planned_completion_days IS NOT NULL
        GROUP BY sr_type_desc
        ORDER BY requests DESC
        LIMIT 20
        """,
    ),
    (
        "C16",
        "Department distribution",
        "Identifies the decision owners. A recommendation has to land on a named "
        "department, not on 'the city'.",
        """
        SELECT
            dept_name,
            COUNT(*) AS requests,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
        FROM raw
        GROUP BY dept_name
        ORDER BY requests DESC
        """,
    ),
(
        "C18",
        "Consistency: does the status flag agree with the presence of a close date?",
        "C13 showed 19,564 requests flagged OPEN while 19,468 have no close date. "
        "The 96-row gap means one of the two fields is wrong on those rows, and the "
        "backlog definition has to say which field it trusts.",
        """
        SELECT
            COALESCE(sr_status_flag, '(blank)') AS status_flag,
            CASE WHEN date_closed IS NULL THEN 'no close date' ELSE 'has close date' END
                AS close_date_present,
            COUNT(*) AS requests
        FROM raw
        GROUP BY status_flag, close_date_present
        ORDER BY requests DESC
        """,
    ),
    (
        "C19",
        "Is the committed completion time a standard per service, or set per request?",
        "C15 showed potholes carrying 60 different commitments between 11 and 313 "
        "days. If most requests of a type share one standard value, the outliers are "
        "exceptions to explain. If they do not, the commitment is set case by case "
        "and an on-time rate measured against it is close to meaningless.",
        """
        WITH top_types AS (
            SELECT sr_type_desc
            FROM raw
            WHERE sr_type_desc IS NOT NULL
            GROUP BY sr_type_desc
            ORDER BY COUNT(*) DESC
            LIMIT 8
        ),
        commitments AS (
            SELECT
                r.sr_type_desc,
                COALESCE(r.priority, '(blank)') AS priority,
                CAST(TRY_CAST(r.planned_completion_days AS DOUBLE) AS INTEGER)
                    AS committed_days,
                COUNT(*) AS requests
            FROM raw r
            JOIN top_types t ON r.sr_type_desc = t.sr_type_desc
            WHERE r.planned_completion_days IS NOT NULL
            GROUP BY r.sr_type_desc, priority, committed_days
        ),
        ranked AS (
            SELECT
                c.*,
                SUM(requests) OVER (PARTITION BY sr_type_desc) AS type_total,
                ROW_NUMBER() OVER (
                    PARTITION BY sr_type_desc ORDER BY requests DESC
                ) AS rn
            FROM commitments c
        )
        SELECT
            sr_type_desc,
            priority,
            committed_days,
            requests,
            ROUND(100.0 * requests / type_total, 1) AS pct_of_type
        FROM ranked
        WHERE rn <= 3
        ORDER BY sr_type_desc, requests DESC
        """,
    ),
(
        "C20",
        "Has the committed completion time changed over the period?",
        "C19 showed several services carry two standard commitments rather than "
        "one. If the city lengthened a commitment partway through the window, an "
        "improving on-time rate could reflect a looser promise rather than faster "
        "service. That distinction decides whether a trend is a finding or an "
        "artefact, so it has to be settled before any trend is reported.",
        """
        WITH top_types AS (
            SELECT sr_type_desc
            FROM raw
            WHERE sr_type_desc IS NOT NULL
            GROUP BY sr_type_desc
            ORDER BY COUNT(*) DESC
            LIMIT 8
        ),
        scoped AS (
            SELECT
                substr(r.date_created, 1, 4) AS year,
                r.sr_type_desc,
                CAST(TRY_CAST(r.planned_completion_days AS DOUBLE) AS INTEGER)
                    AS committed_days
            FROM raw r
            JOIN top_types t ON r.sr_type_desc = t.sr_type_desc
            WHERE r.planned_completion_days IS NOT NULL
              AND r.date_created IS NOT NULL
        ),
        counted AS (
            SELECT sr_type_desc, year, committed_days, COUNT(*) AS requests
            FROM scoped
            GROUP BY sr_type_desc, year, committed_days
        ),
        ranked AS (
            SELECT
                c.*,
                SUM(requests) OVER (PARTITION BY sr_type_desc, year) AS year_total,
                COUNT(*)     OVER (PARTITION BY sr_type_desc, year) AS distinct_values,
                ROW_NUMBER() OVER (
                    PARTITION BY sr_type_desc, year ORDER BY requests DESC
                ) AS rn
            FROM counted c
        )
        SELECT
            sr_type_desc,
            year,
            committed_days                              AS modal_days,
            ROUND(100.0 * requests / year_total, 1)     AS modal_pct,
            distinct_values,
            year_total                                  AS requests_in_year
        FROM ranked
        WHERE rn = 1
        ORDER BY sr_type_desc, year
        """,
    ),
]


def completeness_sql(column_names: list[str]) -> str:
    """
    Build one query that reports the blank rate of every column.

    WHY GENERATE THE SQL: there are 70 columns. Typing 70 CASE expressions by
    hand invites a typo that silently reports the wrong column. Generating them
    from the actual column list guarantees the report covers every column that
    exists, including any the city adds later.
    """
    parts = [
        "SELECT * FROM (",
        "  SELECT 'ROW_COUNT' AS column_name, COUNT(*) AS blank_rows, 0.0 AS blank_pct FROM raw",
    ]
    for name in column_names:
        quoted = f'"{name}"'
        parts.append(
            f"  UNION ALL SELECT '{name}', "
            f"SUM(CASE WHEN {quoted} IS NULL OR {quoted} = '' THEN 1 ELSE 0 END), "
            f"ROUND(100.0 * SUM(CASE WHEN {quoted} IS NULL OR {quoted} = '' THEN 1 ELSE 0 END) "
            f"/ NULLIF(COUNT(*), 0), 2) FROM raw"
        )
    parts.append(") ORDER BY blank_pct DESC, column_name")
    return "\n".join(parts)


def run() -> None:
    source, snapshot_date = db.latest_snapshot()
    manifest_path = source.parent / source.name.replace(".csv.gz", ".manifest.json")
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    print(f"Snapshot : {source.name}")
    print(f"Manifest : {'found' if manifest else 'MISSING'}")
    if manifest:
        print(f"  pulled at  : {manifest.get('pulled_at_utc')}")
        print(f"  manifest rows: {manifest.get('row_count'):,}")
    print()

    con = db.connect(source)
    column_names = db.columns(con)

    manifest_rows = manifest.get("row_count")
    manifest_rows = f"{manifest_rows:,}" if isinstance(manifest_rows, int) else "unknown"

    report_lines: list[str] = [
        "# Validation log: Cincinnati 311 service requests",
        "",
        f"- Snapshot file: `{source.name}`",
        f"- Snapshot date: {snapshot_date}",
        f"- Manifest row count: {manifest_rows}",
        f"- Filter applied: `{manifest.get('filter_applied', 'unknown')}`",
        f"- Log generated: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"- Columns: {len(column_names)}",
        "",
        "This log describes the data. It contains no findings about city "
        "performance. Interpretation begins in step 5.",
        "",
    ]

    failures = 0
    for check_id, title, why, sql in CHECKS:
        print(f"[{check_id}] {title}")
        report_lines += [f"## {check_id}. {title}", "", f"*Why this matters:* {why}", ""]
        try:
            result = con.execute(textwrap.dedent(sql)).fetchdf()
            print(result.to_string(index=False))
            print()
            report_lines += [
                "```sql",
                textwrap.dedent(sql).strip(),
                "```",
                "",
                "```",
                result.to_string(index=False),
                "```",
                "",
            ]
        except Exception as exc:  # noqa: BLE001 - we want the message, not a crash
            failures += 1
            print(f"  CHECK FAILED: {exc}\n")
            report_lines += [
                "**CHECK FAILED**",
                "",
                "```",
                str(exc),
                "```",
                "",
                "```sql",
                textwrap.dedent(sql).strip(),
                "```",
                "",
            ]

    # Completeness is generated rather than hand-written, so it gets its own block.
    print("[C17] Column completeness (blank rate per column)")
    report_lines += [
        "## C17. Column completeness",
        "",
        "*Why this matters:* a column that is 95 percent blank cannot support a "
        "metric, however useful it sounds. This decides which of the 70 columns "
        "enter the model in step 4.",
        "",
    ]
    try:
        completeness = con.execute(completeness_sql(column_names)).fetchdf()
        print(completeness.to_string(index=False))
        print()
        report_lines += ["```", completeness.to_string(index=False), "```", ""]
    except Exception as exc:  # noqa: BLE001
        failures += 1
        print(f"  CHECK FAILED: {exc}\n")
        report_lines += ["**CHECK FAILED**", "", "```", str(exc), "```", ""]

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.REPORTS_DIR / f"validation_log__{snapshot_date}.md"
    out_path.write_text("\n".join(report_lines), encoding="utf-8")

    print("=" * 72)
    print(f"Checks run    : {len(CHECKS) + 1}")
    print(f"Checks failed : {failures}")
    print(f"Log written   : {out_path}")
    if failures:
        print("\nPaste the failed check SQL and its error message to get it fixed.")


if __name__ == "__main__":
    run()
