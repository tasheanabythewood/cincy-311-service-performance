"""
Step 8b. Export pre-aggregated metrics for a dashboard.

WHY A SEPARATE EXPORT RATHER THAN QUERYING LIVE: a dashboard on a static site
has no database behind it. Publishing the 517,287-row fact table would be slow,
pointless and a redistribution question you do not need to answer. Publishing
a few thousand pre-aggregated rows is fast, small, and contains nothing that is
not already a published city statistic.

It also draws a clean line. The aggregates are computed once, here, by the same
definitions everything else uses. The dashboard renders numbers; it does not
calculate them. When a figure on the dashboard disagrees with the case study,
there is exactly one place to look.

TWO FORMATS, TWO AUDIENCES:
  - JSON, for a web dashboard. One file, embedded or fetched, no server.
  - CSV, for Power BI, Tableau or Excel. Same numbers, same grain, so a BI
    tool and the website cannot drift apart.

Usage:
    python -m src.export
"""

from __future__ import annotations

import json

from . import config, db

EXPORT_DIR = config.REPORTS_DIR / "exports"

# Kept deliberately small. Every row here is an aggregate of at least a handful
# of requests, so nothing approaches an individual record.
TOP_N_SERVICES = 25

EXPORTS: dict[str, str] = {

    # Monthly grain, the spine of any time-series view.
    "monthly_by_service": f"""
        WITH top_services AS (
            SELECT s.sr_type
            FROM fact_service_request f
            JOIN dim_service s ON s.service_key = f.service_key
            GROUP BY s.sr_type
            ORDER BY SUM(f.request_count) DESC
            LIMIT {TOP_N_SERVICES}
        )
        SELECT
            s.sr_type,
            MODE(s.service_label)                                  AS service_label,
            MODE(s.modal_committed_days)                           AS committed_days,
            BOOL_OR(s.stable_commitment)                           AS stable_commitment,
            d.year_month,
            d.year,
            d.month_number,
            SUM(f.request_count)                                   AS intake,
            SUM(f.duplicate_count)                                 AS duplicates,
            SUM(f.mature_evaluable_count)                          AS evaluable,
            SUM(f.mature_on_time_count)                            AS on_time,
            SUM(f.open_overdue_count)                              AS open_overdue,
            MEDIAN(CASE WHEN f.outcome IN ('on time','late')
                        THEN f.days_to_close END)                  AS median_days_to_close
        FROM fact_service_request f
        JOIN dim_date    d ON d.date_key    = f.created_date_key
        JOIN dim_service s ON s.service_key = f.service_key
        JOIN top_services t ON t.sr_type    = s.sr_type
        GROUP BY s.sr_type, d.year_month, d.year, d.month_number
        ORDER BY s.sr_type, d.year_month
    """,

    # Who owns the problem.
    "yearly_by_department": """
        SELECT
            o.dept_name,
            d.year,
            SUM(f.request_count)                                   AS intake,
            SUM(f.mature_evaluable_count)                          AS evaluable,
            SUM(f.mature_on_time_count)                            AS on_time,
            SUM(f.open_overdue_count)                              AS open_overdue
        FROM fact_service_request f
        JOIN dim_date         d ON d.date_key = f.created_date_key
        JOIN dim_organization o ON o.org_key  = f.org_key
        GROUP BY o.dept_name, d.year
        HAVING SUM(f.request_count) >= 100
        ORDER BY o.dept_name, d.year
    """,

    # Point-in-time, as of the snapshot date. Not a time series.
    "backlog_by_service": """
        SELECT
            s.sr_type,
            MODE(s.service_label)                                        AS service_label,
            MODE(o.dept_name)                                            AS dept_name,
            SUM(f.open_overdue_count)                                    AS overdue,
            SUM(CASE WHEN f.days_overdue_open <= 90 THEN 1 ELSE 0 END)   AS within_90d,
            SUM(CASE WHEN f.days_overdue_open BETWEEN 91 AND 365
                     THEN 1 ELSE 0 END)                                  AS d91_365,
            SUM(CASE WHEN f.days_overdue_open BETWEEN 366 AND 730
                     THEN 1 ELSE 0 END)                                  AS d1_2yr,
            SUM(CASE WHEN f.days_overdue_open > 730 THEN 1 ELSE 0 END)   AS over_2yr,
            MEDIAN(f.days_overdue_open)                                  AS median_days_overdue
        FROM fact_service_request f
        JOIN dim_service      s ON s.service_key = f.service_key
        JOIN dim_organization o ON o.org_key     = f.org_key
        WHERE f.outcome = 'open, overdue'
        GROUP BY s.sr_type
        HAVING SUM(f.open_overdue_count) >= 25
        ORDER BY overdue DESC
    """,

    # Geography, restricted to the four services with a stable commitment.
    #
    # WHY ONLY THOSE FOUR: a neighbourhood comparison across a mixed basket of
    # services confounds WHAT a neighbourhood reports with HOW FAST it is
    # handled. Holding the service constant is what makes the comparison mean
    # anything, and a dashboard filter is exactly where someone would otherwise
    # mix them by accident.
    "neighborhood_stable_services": """
        SELECT
            n.neighborhood,
            s.sr_type,
            MODE(s.service_label)                                  AS service_label,
            MODE(s.modal_committed_days)                           AS committed_days,
            SUM(f.request_count)                                   AS intake,
            SUM(f.mature_evaluable_count)                          AS evaluable,
            SUM(f.mature_on_time_count)                            AS on_time,
            MEDIAN(CASE WHEN f.outcome IN ('on time','late')
                        THEN f.days_to_close END)                  AS median_days_to_close
        FROM fact_service_request f
        JOIN dim_service      s ON s.service_key      = f.service_key
        JOIN dim_neighborhood n ON n.neighborhood_key = f.neighborhood_key
        WHERE s.stable_commitment
        GROUP BY n.neighborhood, s.sr_type
        HAVING SUM(f.mature_evaluable_count) >= 100
        ORDER BY n.neighborhood, s.sr_type
    """,

    # Intake channel, for a simple operational view.
    "channel_by_year": """
        SELECT
            f.method_received,
            d.year,
            SUM(f.request_count)                                   AS intake,
            SUM(f.duplicate_count)                                 AS duplicates,
            SUM(f.mature_evaluable_count)                          AS evaluable,
            SUM(f.mature_on_time_count)                            AS on_time
        FROM fact_service_request f
        JOIN dim_date d ON d.date_key = f.created_date_key
        GROUP BY f.method_received, d.year
        HAVING SUM(f.request_count) >= 100
        ORDER BY f.method_received, d.year
    """,
}


def run() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    source, snapshot_date = db.latest_snapshot()
    con = db.connect_warehouse(source)

    payload: dict[str, object] = {
        "meta": {
            "source": "City of Cincinnati 311 Non-Emergency Service Requests",
            "snapshot_file": source.name,
            "snapshot_date": snapshot_date,
            "window_start": config.WINDOW_START,
            "window_end": config.WINDOW_END,
            "total_requests": 0,
            # Anything reading this file needs to know the rules behind the
            # numbers, not just the numbers.
            "notes": [
                "Rates are SUM(on_time) / SUM(evaluable). Never average a percentage.",
                "evaluable counts only requests whose committed date had passed as of "
                "the snapshot date. Requests still inside their window are excluded "
                "because their outcome is unknown.",
                "Open requests already past their committed date count as misses.",
                "Duplicates are excluded from service-delivery measures and reported "
                "separately as an intake measure.",
                "2026 covers January to August only.",
                "Definitions: reports/metric_dictionary.md",
            ],
        }
    }

    total = con.execute("SELECT COUNT(*) FROM fact_service_request").fetchone()[0]
    payload["meta"]["total_requests"] = int(total)  # type: ignore[index]

    for name, sql in EXPORTS.items():
        frame = con.execute(sql).fetchdf()
        csv_path = EXPORT_DIR / f"{name}.csv"
        frame.to_csv(csv_path, index=False)
        # JSON records, which is what a browser wants without a parsing step.
        payload[name] = json.loads(frame.to_json(orient="records"))
        print(f"  {name:<32}{len(frame):>6,} rows  ->  {csv_path.name}")

    json_path = EXPORT_DIR / "metrics.json"
    json_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    size_kb = json_path.stat().st_size / 1024

    con.close()
    print(f"\n  metrics.json  {size_kb:,.0f} KB")
    if size_kb > 2048:
        print("  WARNING: over 2 MB. Trim TOP_N_SERVICES or drop a table before "
              "embedding this in a page.")
    print(f"  CSVs and JSON in {EXPORT_DIR}")


if __name__ == "__main__":
    run()
