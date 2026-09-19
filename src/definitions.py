"""
Step 3. The locked definitions.

WHY THIS FILE EXISTS: every number in the dashboard, the case study, and the
website has to come from one definition, written once. The alternative is the
same metric computed slightly differently in three places, which is how a
dashboard ends up with two on-time rates that disagree and nobody can say
which is right.

The SQL text below is the definition. `reports/metric_dictionary.md` explains
it in prose for a reader. If the two ever disagree, this file wins, because
this is what actually runs.

NOTHING HERE PRODUCES A FINDING. It builds the population and labels each
request's outcome. Interpretation starts in step 5.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Scope, confirmed 2026-09-18
# ---------------------------------------------------------------------------

# Services whose committed completion time held steady across 2023 to 2026
# (check C20). Only these support an on-time TREND, because in the others the
# commitment itself changed mid-window and a moving promise would masquerade
# as changing performance.
# Keyed by sr_type, the service CODE, not by description.
#
# WHY THE CHANGE: check A0 found 695 code/description pairs across only 524
# codes, and A0c showed the extra descriptions are concurrent, not sequential.
# LITR-PRV carries both "LITTER, PRIVATE PROPERTY" and
# "LITTER,  PRIVATE PROPERTY", which differ by one space. Matching on the
# description text silently dropped 4,598 requests, 29.1 percent of that
# service. The code is the stable identity; the description is a label that
# varies. Pothole repair had the same defect at a much smaller scale.
STABLE_COMMITMENT_SERVICES: dict[str, tuple[str, int]] = {
    "PTHOLE":   ("Pothole repair", 12),
    "BLD-RES":  ("Building, residential", 365),
    "TLGR-PRV": ("Tall grass and weeds, private property", 45),
    "LITR-PRV": ("Litter, private property", 45),
}

# Services where the commitment changed during the window. Named explicitly so
# that a reader can see they were considered and excluded on evidence, not
# forgotten. See check C20.
CHANGED_COMMITMENT_SERVICES: dict[str, str] = {
    "RF-COLLT": "7 days in 2023, 1 day from 2024",
    "MTL-FRN": "single 14-day commitment, then a 14/30 day split from 2025",
    "311ASSIT": "commitment stable, but volume fell about 72 percent in 2026",
}

# Volume migrated between these two types after 2024, so neither is comparable
# over time on its own. Analyse them as one family or not at all.
# One CODE, not two services. A0c showed "METAL FURNITURE, SPEC COLLECTN" and
# "TRASH, BULK ITEM PICK-UP" are two concurrent descriptions of MTL-FRN, both
# in active use from July 2024 onward. An earlier reading of check C20 called
# this a new service type absorbing volume from an old one. That was wrong:
# nothing was introduced, a second label was added to an existing code.
BULK_COLLECTION_FAMILY: tuple[str, ...] = ("MTL-FRN",)

# Closure codes the publisher does not define anywhere in the data dictionary.
# Every one of these is treated as a completed closure in the primary metric,
# and the sensitivity test in metrics.py shows what happens if that assumption
# is wrong. Do not quietly exclude a code on the strength of its abbreviation.
UNDEFINED_CLOSURE_CODES: tuple[str, ...] = (
    "CLOS-NO",
    "ABAT-OWN",
    "CLOS-RI",
    "CLOS-EXP",
    "CLOS-EOY",
)

# The one closure code excluded from service-delivery metrics. A duplicate is
# not an independent unit of work, so counting it would inflate both demand and
# the on-time rate. It stays in the intake population, where it is real volume
# that the call centre handled, and its rate is reported as a finding.
DUPLICATE_CODE = "DUPLICAT"


# ---------------------------------------------------------------------------
# The analysis view
# ---------------------------------------------------------------------------

def analysis_view_sql(as_of_date: str, source_table: str = "raw") -> str:
    """
    Build the SQL that turns the raw text snapshot into a typed, labelled
    analysis view.

    as_of_date is the snapshot date from the manifest, NOT today's date.

    WHY NOT CURRENT_DATE: whether an open request counts as overdue depends on
    the date you ask. Using CURRENT_DATE means rerunning this next March
    silently changes the answer on an identical input file, and no number in
    the case study could be reproduced. Pinning it to the snapshot date makes
    every figure a statement about a specific moment, which is what a
    defensible metric is.
    """
    stable_list = ", ".join(f"'{c}'" for c in STABLE_COMMITMENT_SERVICES)
    family_list = ", ".join(f"'{c}'" for c in BULK_COLLECTION_FAMILY)

    return f"""
CREATE OR REPLACE VIEW analysis AS
WITH typed AS (
    SELECT
        sr_number,
        sr_type,
        sr_type_desc,
        -- Collapse repeated whitespace so label variants that differ only by
        -- spacing group together for display. The CODE remains the identity.
        regexp_replace(trim(COALESCE(sr_type_desc, '(not stated)')), '\\s+', ' ', 'g')
            AS service_label,
        COALESCE(priority, '(not stated)')        AS priority,
        COALESCE(dept_name, '(not stated)')       AS dept_name,
        COALESCE(group_title, '(not stated)')     AS group_title,
        COALESCE(neighborhood, '(not stated)')    AS neighborhood,
        zipcode,
        COALESCE(method_received, '(not stated)') AS method_received,
        sr_status,
        sr_status_flag,

        -- Dates arrive as ISO text with a zeroed time component. Slice to the
        -- first 10 characters and cast; TRY_CAST yields NULL rather than
        -- raising on a malformed value, so one bad row cannot stop the build.
        TRY_CAST(substr(date_created, 1, 10)     AS DATE) AS created_date,
        TRY_CAST(substr(date_closed, 1, 10)      AS DATE) AS closed_date,
        TRY_CAST(substr(planned_end_date, 1, 10) AS DATE) AS due_date,

        CAST(TRY_CAST(planned_completion_days AS DOUBLE) AS INTEGER)
            AS committed_days,

        (date_revised_completion IS NOT NULL) AS deadline_revised
    FROM {source_table}
),
flagged AS (
    SELECT
        *,
        (sr_status = '{DUPLICATE_CODE}')                      AS is_duplicate,
        (closed_date IS NOT NULL)                             AS is_closed,
        (sr_type IN ({stable_list}))                          AS stable_commitment_service,
        (sr_type IN ({family_list}))                          AS bulk_collection_family,

        -- MATURITY. A request is only a fair test of the commitment once its
        -- committed date has passed. Until then it can be counted on time (if
        -- it closed early) but it cannot possibly be counted late, so a recent
        -- cohort shows only its fast closers.
        --
        -- Left uncorrected this produces a rising on-time trend out of nothing.
        -- A 365-day service looked like 100 percent on time in 2026 purely
        -- because no 2026 request is due until 2027. Every trend must filter on
        -- this flag; a point-in-time rate need not.
        (due_date IS NOT NULL AND due_date <= DATE '{as_of_date}') AS is_mature,

        -- Elapsed calendar days. Negative days_past_due means finished early.
        date_diff('day', created_date, closed_date)           AS days_to_close,
        date_diff('day', due_date, closed_date)               AS days_past_due,
        date_diff('day', due_date, DATE '{as_of_date}')       AS days_overdue_open
    FROM typed
)
SELECT
    *,
    -- Outcome is mutually exclusive and exhaustive: every row in the snapshot
    -- lands in exactly one bucket. metrics.py proves this by reconciling the
    -- bucket totals back to the manifest row count.
    CASE
        -- Unusable for timeliness, whatever else is true of the row.
        WHEN created_date IS NULL OR due_date IS NULL
            THEN 'excluded: no commitment recorded'
        WHEN closed_date IS NOT NULL AND closed_date < created_date
            THEN 'excluded: closed before created'

        -- Real intake, but not an independent unit of service delivery.
        WHEN is_duplicate
            THEN 'excluded: duplicate request'

        -- Resolved, outcome known.
        WHEN closed_date IS NOT NULL AND closed_date <= due_date
            THEN 'on time'
        WHEN closed_date IS NOT NULL AND closed_date > due_date
            THEN 'late'

        -- Unresolved and already past the committed date: definitively late,
        -- even though no closure has been recorded.
        WHEN closed_date IS NULL AND due_date < DATE '{as_of_date}'
            THEN 'open, overdue'

        -- Unresolved and still inside the committed window. The outcome is
        -- genuinely unknown, so this row is censored and must be excluded from
        -- the rate rather than counted either way.
        ELSE 'open, not yet due'
    END AS outcome
FROM flagged
"""


# ---------------------------------------------------------------------------
# Metric expressions
#
# Each entry is (metric name, SQL expression, one-line definition). They are
# written against the `analysis` view above. Keeping them here means the
# dashboard in step 4 and the analysis in step 5 use the identical expression.
# ---------------------------------------------------------------------------

METRICS: list[tuple[str, str, str]] = [
    (
        "requests_received",
        "COUNT(*)",
        "Every request in the snapshot, duplicates included. Measures intake "
        "load on the 311 service, not work performed.",
    ),
    (
        "duplicate_rate",
        "100.0 * SUM(CASE WHEN is_duplicate THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0)",
        "Share of intake closed as a duplicate. An intake-efficiency measure, "
        "not a service-delivery one.",
    ),
    (
        "service_requests",
        "SUM(CASE WHEN NOT is_duplicate THEN 1 ELSE 0 END)",
        "Requests representing independent units of work. Intake minus duplicates.",
    ),
    (
        "evaluable_requests",
        "SUM(CASE WHEN outcome IN ('on time', 'late', 'open, overdue') "
        "THEN 1 ELSE 0 END)",
        "Denominator of the on-time rate: requests whose timeliness outcome is "
        "known as of the snapshot date.",
    ),
    (
        "on_time_requests",
        "SUM(CASE WHEN outcome = 'on time' THEN 1 ELSE 0 END)",
        "Closed on or before the committed completion date.",
    ),
    (
        "on_time_rate",
        "100.0 * SUM(CASE WHEN outcome = 'on time' THEN 1 ELSE 0 END) "
        "/ NULLIF(SUM(CASE WHEN outcome IN ('on time', 'late', 'open, overdue') "
        "THEN 1 ELSE 0 END), 0)",
        "On-time requests as a percentage of evaluable requests. Open requests "
        "already past their committed date count as misses.",
    ),
    (
        "open_overdue",
        "SUM(CASE WHEN outcome = 'open, overdue' THEN 1 ELSE 0 END)",
        "Unresolved requests already past their committed completion date.",
    ),
    (
        "median_days_to_close",
        "MEDIAN(CASE WHEN outcome IN ('on time', 'late') THEN days_to_close END)",
        "Median calendar days from submission to closure, closed requests only. "
        "Median rather than mean because the distribution has a long tail.",
    ),
    (
        "median_days_overdue_open",
        "MEDIAN(CASE WHEN outcome = 'open, overdue' THEN days_overdue_open END)",
        "Median days an overdue open request has been past its committed date. "
        "Measures how stale the backlog is, not how large.",
    ),
    (
        "deadline_revision_rate",
        "100.0 * SUM(CASE WHEN deadline_revised THEN 1 ELSE 0 END) "
        "/ NULLIF(COUNT(*), 0)",
        "Share of requests whose completion date was revised. Reported so a "
        "reader can judge whether the committed date was a moving target.",
    ),
]
