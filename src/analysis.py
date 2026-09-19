"""
Step 5. The analysis.

Every query here runs against the star schema built in step 4, not against the
raw file. That is the point of having built it: if the model cannot answer the
questions the project was scoped around, the model was wrong.

WHAT THIS STEP PRODUCES: tables and the findings they support. It does not
produce the recommendation, which is step 7, and it does not produce the
charts, which are step 8. Keeping analysis separate from recommendation means
the evidence can be checked without arguing about the conclusion.

RULES CARRIED FORWARD FROM THE METRIC DICTIONARY:
  - Rates are computed as SUM(numerator) / SUM(denominator), never as an
    average of percentages.
  - The on-time TREND is reported only for the four stable-commitment
    services. Demand and backlog are reported across everything.
  - Open requests past their committed date count as misses. Open requests
    still inside their window are censored and excluded.

Usage:
    python -m src.analysis
"""

from __future__ import annotations

import textwrap

from . import config, db

# Minimum volume before a group is reported. Small denominators produce
# dramatic-looking rates that are mostly noise, and a neighbourhood with nine
# requests at 55 percent tells you nothing about that neighbourhood.
MIN_GROUP_VOLUME = 150


ANALYSES: list[tuple[str, str, str, str]] = [
    (
        "A0",
        "Integrity: is the service code one-to-one with its description?",
        "dim_service holds 695 service types. If a single sr_type maps to more "
        "than one description, grouping by code and grouping by description give "
        "different answers, and any chart built on one of them is arguable.",
        """
        SELECT
            COUNT(*)                        AS rows_in_dim,
            COUNT(DISTINCT sr_type)         AS distinct_codes,
            COUNT(DISTINCT sr_type_desc)    AS distinct_descriptions
        FROM dim_service
        WHERE service_key <> -1
        """,
    ),
    (
        "A0b",
        "Service codes carrying more than one description",
        "Lists the offenders, if A0 found any. A code whose description changed "
        "over time is a slowly changing dimension, and the analysis has to pick "
        "one representation and say so.",
        """
        SELECT sr_type, COUNT(*) AS descriptions, MIN(sr_type_desc) AS example_a,
               MAX(sr_type_desc) AS example_b
        FROM dim_service
        WHERE service_key <> -1
        GROUP BY sr_type
        HAVING COUNT(*) > 1
        ORDER BY descriptions DESC, sr_type
        LIMIT 10
        """,
    ),
    (
        "A0c",
        "Codes behind the nine services in scope, with their date spans",
        "A0b showed MTL-FRN carrying both a metal-furniture description and a "
        "bulky-item one, and RF-COLLT carrying both trash collection descriptions. "
        "If those are the same code relabelled over time, then the volume "
        "'migration' reported from check C20 is a rename, not a reclassification, "
        "and that finding has to be withdrawn. Date spans settle it: a rename "
        "gives consecutive, non-overlapping spans.",
        """
        WITH scoped_codes AS (
            SELECT DISTINCT sr_type
            FROM dim_service
            WHERE sr_type_desc IN (
                'METAL FURNITURE, SPEC COLLECTN',
                'TRASH, BULK ITEM PICK-UP',
                'TRASH, REQUEST FOR COLLECTION',
                'TRASH, MISSED COLLECTION',
                'POTHOLE, REPAIR',
                'BUILDING, RESIDENTIAL',
                'TALL GRASS/WEEDS, PRIVATE PROP',
                'LITTER, PRIVATE PROPERTY',
                '311 ASSISTANCE'
            )
        )
        SELECT
            s.sr_type,
            s.sr_type_desc,
            SUM(f.request_count)   AS requests,
            MIN(d.full_date)       AS first_seen,
            MAX(d.full_date)       AS last_seen,
            MODE(f.committed_days) AS modal_days
        FROM fact_service_request f
        JOIN dim_service s ON s.service_key = f.service_key
        JOIN dim_date    d ON d.date_key    = f.created_date_key
        JOIN scoped_codes c ON c.sr_type    = s.sr_type
        GROUP BY s.sr_type, s.sr_type_desc
        ORDER BY s.sr_type, first_seen
        """,
    ),
    (
        "A0d",
        "Across all multi-description codes: rename or concurrent variants?",
        "Sizes the problem. Sequential spans mean the description was changed and "
        "the service is continuous, so grouping by description splits one service "
        "into several across time. Overlapping spans mean genuinely distinct "
        "sub-services sharing a code, which is the opposite problem.",
        """
        WITH multi AS (
            SELECT sr_type
            FROM dim_service
            WHERE service_key <> -1
            GROUP BY sr_type
            HAVING COUNT(*) > 1
        ),
        spans AS (
            SELECT
                s.sr_type,
                s.sr_type_desc,
                SUM(f.request_count) AS requests,
                MIN(d.full_date)     AS first_seen,
                MAX(d.full_date)     AS last_seen
            FROM fact_service_request f
            JOIN dim_service s ON s.service_key = f.service_key
            JOIN dim_date    d ON d.date_key    = f.created_date_key
            JOIN multi       m ON m.sr_type     = s.sr_type
            GROUP BY s.sr_type, s.sr_type_desc
        ),
        overlap AS (
            SELECT
                a.sr_type,
                SUM(CASE WHEN a.first_seen <= b.last_seen
                          AND b.first_seen <= a.last_seen
                         THEN 1 ELSE 0 END) AS overlapping_pairs
            FROM spans a
            JOIN spans b
              ON a.sr_type = b.sr_type
             AND a.sr_type_desc < b.sr_type_desc
            GROUP BY a.sr_type
        ),
        totals AS (
            SELECT sr_type, SUM(requests) AS requests FROM spans GROUP BY sr_type
        )
        SELECT
            CASE WHEN o.overlapping_pairs = 0
                 THEN 'sequential: description changed over time'
                 ELSE 'concurrent: variants share one code' END AS pattern,
            COUNT(*)                                            AS codes,
            SUM(t.requests)                                     AS requests,
            ROUND(100.0 * SUM(t.requests) / 517287.0, 1)        AS pct_of_all
        FROM overlap o
        JOIN totals t ON t.sr_type = o.sr_type
        GROUP BY pattern
        ORDER BY requests DESC
        """,
    ),
    (
        "A1",
        "Demand and outcomes by year, all services",
        "Context for everything else. Demand rose steadily across the window, so "
        "a flat on-time rate would represent more work delivered at the same "
        "standard, not standing still.",
        """
        SELECT
            d.year,
            SUM(f.request_count)                                        AS intake,
            SUM(f.duplicate_count)                                      AS duplicates,
            ROUND(100.0 * SUM(f.duplicate_count)
                  / NULLIF(SUM(f.request_count), 0), 1)                 AS duplicate_pct,
            SUM(f.evaluable_count)                                      AS evaluable,
            ROUND(100.0 * SUM(f.on_time_count)
                  / NULLIF(SUM(f.evaluable_count), 0), 1)               AS on_time_pct,
            SUM(f.open_overdue_count)                                   AS open_overdue
        FROM fact_service_request f
        JOIN dim_date d ON d.date_key = f.created_date_key
        GROUP BY d.year
        ORDER BY d.year
        """,
    ),
    (
        "A2",
        "On-time trend, stable-commitment services only",
        "The headline trend. Restricted to the four services whose committed "
        "completion time held steady across the window, so a change here is "
        "performance rather than a moving promise. 2026 covers January to August "
        "only.",
        """
        SELECT
            d.year,
            SUM(f.request_count)                                        AS intake,
            SUM(f.mature_evaluable_count)                               AS mature_evaluable,
            -- Coverage: what share of the year's intake has actually reached
            -- its committed date. A low value means the year is not yet
            -- comparable and its rate should not be plotted.
            ROUND(100.0 * SUM(f.mature_evaluable_count)
                  / NULLIF(SUM(f.request_count), 0), 1)                 AS pct_mature,
            ROUND(100.0 * SUM(f.mature_on_time_count)
                  / NULLIF(SUM(f.mature_evaluable_count), 0), 1)        AS on_time_pct,
            SUM(f.closed_late_count)                                    AS closed_late,
            SUM(f.open_overdue_count)                                   AS never_closed,
            -- The maturity fix removed the censoring bias but not a second
            -- problem: if one service contributes no mature requests in a year,
            -- the combined rate is computed over a different mix of services
            -- each year and the years are not comparable. This column makes
            -- that visible instead of letting it hide inside the average.
            COUNT(DISTINCT CASE WHEN f.mature_evaluable_count = 1
                                THEN s.sr_type END)                     AS services_present
        FROM fact_service_request f
        JOIN dim_date    d ON d.date_key    = f.created_date_key
        JOIN dim_service s ON s.service_key = f.service_key
        WHERE s.stable_commitment
        GROUP BY d.year
        ORDER BY d.year
        """,
    ),
    (
        "A3",
        "On-time trend by service and year",
        "Where the movement in A2 comes from. A citywide figure can hide one "
        "service improving while another collapses.",
        """
        SELECT
            s.sr_type,
            s.modal_committed_days                                      AS days,
            d.year,
            SUM(f.request_count)                                        AS intake,
            SUM(f.mature_evaluable_count)                               AS mature_evaluable,
            ROUND(100.0 * SUM(f.mature_evaluable_count)
                  / NULLIF(SUM(f.request_count), 0), 1)                 AS pct_mature,
            ROUND(100.0 * SUM(f.mature_on_time_count)
                  / NULLIF(SUM(f.mature_evaluable_count), 0), 1)        AS on_time_pct,
            SUM(f.open_overdue_count)                                   AS never_closed
        FROM fact_service_request f
        JOIN dim_date    d ON d.date_key    = f.created_date_key
        JOIN dim_service s ON s.service_key = f.service_key
        WHERE s.stable_commitment
          AND s.modal_committed_days IS NOT NULL
        GROUP BY s.sr_type, s.modal_committed_days, d.year
        ORDER BY s.sr_type, d.year
        """,
    ),
    (
        "A9",
        "Which services caused the 2025 citywide drop?",
        "A1 shows the all-service on-time rate falling 13.5 points in 2025 and "
        "recovering in 2026, while A2 shows the four stable services rising every "
        "year. The drop is therefore entirely outside the stable set. This ranks "
        "services by their contribution to it, weighting the rate change by volume "
        "so that a large service moving a little outranks a tiny one collapsing.",
        """
        WITH yearly AS (
            SELECT
                s.sr_type,
                MODE(s.service_label)          AS service_label,
                d.year,
                SUM(f.mature_evaluable_count)  AS evaluable,
                SUM(f.mature_on_time_count)    AS on_time
            FROM fact_service_request f
            JOIN dim_date    d ON d.date_key    = f.created_date_key
            JOIN dim_service s ON s.service_key = f.service_key
            GROUP BY s.sr_type, d.year
        ),
        pivoted AS (
            SELECT
                sr_type,
                MODE(service_label) AS service_label,
                SUM(CASE WHEN year = 2024 THEN evaluable END) AS eval_2024,
                SUM(CASE WHEN year = 2024 THEN on_time   END) AS ontime_2024,
                SUM(CASE WHEN year = 2025 THEN evaluable END) AS eval_2025,
                SUM(CASE WHEN year = 2025 THEN on_time   END) AS ontime_2025
            FROM yearly
            GROUP BY sr_type
        )
        SELECT
            service_label,
            eval_2024,
            ROUND(100.0 * ontime_2024 / NULLIF(eval_2024, 0), 1) AS pct_2024,
            eval_2025,
            ROUND(100.0 * ontime_2025 / NULLIF(eval_2025, 0), 1) AS pct_2025,
            ROUND(100.0 * ontime_2025 / NULLIF(eval_2025, 0)
                  - 100.0 * ontime_2024 / NULLIF(eval_2024, 0), 1) AS change_pts,
            -- Requests that would have been on time in 2025 had the service
            -- held its 2024 rate. This is the volume-weighted contribution.
            ROUND(eval_2025 * (ontime_2024 / NULLIF(eval_2024, 0))
                  - ontime_2025, 0)                                AS shortfall
        FROM pivoted
        WHERE eval_2024 >= 500 AND eval_2025 >= 500
        ORDER BY shortfall DESC
        LIMIT 15
        """,
    ),
    (
        "A10",
        "MTL-FRN decomposed: is the 2025 drop real service degradation?",
        "MTL-FRN is 117,670 requests, 22.7 percent of the file, and accounts for "
        "69 percent of the 2025 citywide shortfall. Its on-time rate fell 28.4 "
        "points on flat volume. A LONGER commitment appeared in 2025, which "
        "should have raised the rate, not cut it. Splitting by commitment tier "
        "and by label separates two possibilities: the service genuinely "
        "degraded, or a slower sub-service arrived carrying its own label and "
        "its own commitment.",
        """
        SELECT
            d.year,
            s.service_label,
            f.committed_days,
            SUM(f.request_count)                                        AS intake,
            SUM(f.mature_evaluable_count)                               AS mature_evaluable,
            ROUND(100.0 * SUM(f.mature_on_time_count)
                  / NULLIF(SUM(f.mature_evaluable_count), 0), 1)        AS on_time_pct,
            MEDIAN(CASE WHEN f.outcome IN ('on time','late')
                        THEN f.days_to_close END)                       AS median_days
        FROM fact_service_request f
        JOIN dim_date    d ON d.date_key    = f.created_date_key
        JOIN dim_service s ON s.service_key = f.service_key
        WHERE s.sr_type = 'MTL-FRN'
          AND f.committed_days IS NOT NULL
        GROUP BY d.year, s.service_label, f.committed_days
        HAVING SUM(f.request_count) >= 100
        ORDER BY d.year, s.service_label, f.committed_days
        """,
    ),
    (
        "A11",
        "MTL-FRN month by month: step change or gradual slide?",
        "A sudden drop in one month points at a policy, system or contract "
        "change. A gradual slide points at capacity falling behind. The shape of "
        "the decline decides which recommendation is even plausible.",
        """
        SELECT
            d.year_month,
            SUM(f.request_count)                                        AS intake,
            SUM(f.mature_evaluable_count)                               AS mature_evaluable,
            ROUND(100.0 * SUM(f.mature_on_time_count)
                  / NULLIF(SUM(f.mature_evaluable_count), 0), 1)        AS on_time_pct,
            MEDIAN(CASE WHEN f.outcome IN ('on time','late')
                        THEN f.days_to_close END)                       AS median_days,
            ROUND(100.0 * SUM(CASE WHEN f.committed_days = 30 THEN 1 ELSE 0 END)
                  / NULLIF(SUM(f.request_count), 0), 1)                 AS pct_on_30day
        FROM fact_service_request f
        JOIN dim_date    d ON d.date_key    = f.created_date_key
        JOIN dim_service s ON s.service_key = f.service_key
        WHERE s.sr_type = 'MTL-FRN'
          AND d.year >= 2024
        GROUP BY d.year_month
        ORDER BY d.year_month
        """,
    ),
    (
        "A4",
        "The overdue backlog, by age band and service",
        "How stale the backlog is, across all services. A request a month past "
        "its date and one three years past it are both misses, but only one of "
        "them is plausibly still live work.",
        f"""
        SELECT
            s.sr_type,
            MODE(s.service_label)                                       AS service_label,
            SUM(f.open_overdue_count)                                   AS overdue,
            SUM(CASE WHEN f.days_overdue_open <= 90  THEN 1 ELSE 0 END) AS within_90d,
            SUM(CASE WHEN f.days_overdue_open BETWEEN 91 AND 365
                     THEN 1 ELSE 0 END)                                 AS d91_365,
            SUM(CASE WHEN f.days_overdue_open BETWEEN 366 AND 730
                     THEN 1 ELSE 0 END)                                 AS d1_2yr,
            SUM(CASE WHEN f.days_overdue_open > 730 THEN 1 ELSE 0 END)  AS over_2yr,
            MEDIAN(f.days_overdue_open)                                 AS median_days_overdue
        FROM fact_service_request f
        JOIN dim_service s ON s.service_key = f.service_key
        WHERE f.outcome = 'open, overdue'
        GROUP BY s.sr_type
        HAVING SUM(f.open_overdue_count) >= {MIN_GROUP_VOLUME}
        ORDER BY overdue DESC
        LIMIT 20
        """,
    ),
    (
        "A5",
        "The overdue backlog by department",
        "A recommendation has to land on a named decision owner. This says which "
        "department would have to act.",
        """
        SELECT
            o.dept_name,
            SUM(f.request_count)                                        AS intake,
            SUM(f.open_overdue_count)                                   AS overdue,
            ROUND(100.0 * SUM(f.open_overdue_count)
                  / NULLIF(SUM(f.request_count), 0), 1)                 AS pct_of_own_intake,
            ROUND(100.0 * SUM(f.open_overdue_count)
                  / NULLIF(SUM(SUM(f.open_overdue_count)) OVER (), 0), 1)
                                                                        AS pct_of_all_overdue,
            ROUND(100.0 * SUM(f.on_time_count)
                  / NULLIF(SUM(f.evaluable_count), 0), 1)               AS on_time_pct
        FROM fact_service_request f
        JOIN dim_organization o ON o.org_key = f.org_key
        GROUP BY o.dept_name
        ORDER BY overdue DESC
        LIMIT 15
        """,
    ),
    (
        "A6",
        "Pothole repair on-time rate by neighbourhood",
        "Neighbourhood comparison, holding service mix constant by restricting to "
        "ONE service with a stable 12-day commitment. Comparing neighbourhoods "
        "across a mixed basket of services would confound where requests come "
        "from with how fast they are handled, which is the single easiest way to "
        "turn an operational finding into an unfounded claim about fairness.",
        f"""
        SELECT
            n.neighborhood,
            SUM(f.evaluable_count)                                      AS evaluable,
            ROUND(100.0 * SUM(f.on_time_count)
                  / NULLIF(SUM(f.evaluable_count), 0), 1)               AS on_time_pct,
            MEDIAN(CASE WHEN f.outcome IN ('on time','late')
                        THEN f.days_to_close END)                       AS median_days
        FROM fact_service_request f
        JOIN dim_service      s ON s.service_key      = f.service_key
        JOIN dim_neighborhood n ON n.neighborhood_key = f.neighborhood_key
        WHERE s.sr_type = 'PTHOLE'
        GROUP BY n.neighborhood
        HAVING SUM(f.evaluable_count) >= {MIN_GROUP_VOLUME}
        ORDER BY on_time_pct
        """,
    ),
    (
        "A7",
        "Duplicate rate by service",
        "Duplicates are intake cost with no service delivered. A high rate points "
        "at a reporting experience that does not tell a resident the problem is "
        "already known, which is a cheaper thing to fix than crew capacity.",
        f"""
        SELECT
            s.sr_type,
            MODE(s.service_label)                                       AS service_label,
            SUM(f.request_count)                                        AS intake,
            SUM(f.duplicate_count)                                      AS duplicates,
            ROUND(100.0 * SUM(f.duplicate_count)
                  / NULLIF(SUM(f.request_count), 0), 1)                 AS duplicate_pct
        FROM fact_service_request f
        JOIN dim_service s ON s.service_key = f.service_key
        GROUP BY s.sr_type
        HAVING SUM(f.request_count) >= {MIN_GROUP_VOLUME * 10}
        ORDER BY duplicate_pct DESC
        LIMIT 15
        """,
    ),
    (
        "A8",
        "Intake channel and outcome, stable-commitment services",
        "Whether how a request arrives is associated with how it ends. Any "
        "difference here is an association, not a cause: channels are chosen by "
        "different people reporting different problems.",
        """
        SELECT
            f.method_received,
            SUM(f.request_count)                                        AS intake,
            ROUND(100.0 * SUM(f.duplicate_count)
                  / NULLIF(SUM(f.request_count), 0), 1)                 AS duplicate_pct,
            SUM(f.evaluable_count)                                      AS evaluable,
            ROUND(100.0 * SUM(f.on_time_count)
                  / NULLIF(SUM(f.evaluable_count), 0), 1)               AS on_time_pct
        FROM fact_service_request f
        JOIN dim_service s ON s.service_key = f.service_key
        WHERE s.stable_commitment
        GROUP BY f.method_received
        ORDER BY intake DESC
        """,
    ),
]


def run() -> None:
    source, snapshot_date = db.latest_snapshot()
    print(f"Warehouse : {config.WAREHOUSE}")
    print(f"As-of     : {snapshot_date}")
    print("All queries run against the star schema, not the raw file.\n")

    con = db.connect_warehouse(source)

    lines: list[str] = [
        "# Analysis tables",
        "",
        f"- Warehouse: `{config.WAREHOUSE.name}`",
        f"- As-of date: {snapshot_date}",
        "- Every rate is SUM(numerator) / SUM(denominator), never an average of "
        "percentages.",
        "- On-time trends cover the four stable-commitment services only. See "
        "`reports/metric_dictionary.md` section 5.",
        "- 2026 covers January to August only.",
        "",
    ]

    failures = 0
    for code, title, why, sql in ANALYSES:
        print("=" * 72)
        print(f"[{code}] {title}")
        print("=" * 72)
        lines += [f"## {code}. {title}", "", f"*Why:* {why}", ""]
        try:
            frame = con.execute(textwrap.dedent(sql)).fetchdf()
            rendered = frame.to_string(index=False)
            print(rendered + "\n")
            lines += ["```sql", textwrap.dedent(sql).strip(), "```", "",
                      "```", rendered, "```", ""]
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  QUERY FAILED: {exc}\n")
            lines += ["**QUERY FAILED**", "", "```", str(exc), "```", "",
                      "```sql", textwrap.dedent(sql).strip(), "```", ""]

    out = config.REPORTS_DIR / f"analysis_tables__{snapshot_date}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    con.close()

    print("=" * 72)
    print(f"Analyses run    : {len(ANALYSES)}")
    print(f"Analyses failed : {failures}")
    print(f"Tables written  : {out}")


if __name__ == "__main__":
    run()
