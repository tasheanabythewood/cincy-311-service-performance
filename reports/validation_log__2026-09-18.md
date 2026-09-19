# Validation log: Cincinnati 311 service requests

- Snapshot file: `service_requests__2026-09-18.csv.gz`
- Snapshot date: 2026-09-18
- Manifest row count: 517,287
- Filter applied: `date_created >= '2023-01-01T00:00:00.000' AND date_created <= '2026-08-31T23:59:59.999'`
- Log generated: 2026-09-18T16:07:15
- Columns: 70

This log describes the data. It contains no findings about city performance. Interpretation begins in step 5.

## C01. Row count

*Why this matters:* Must match the manifest and the count the API reported. A mismatch means the download was truncated or the paging duplicated rows.

```sql
SELECT COUNT(*) AS row_count FROM raw
```

```
 row_count
    517287
```

## C02. Grain: is sr_number unique?

*Why this matters:* The whole model assumes one row per service request. If it is not, every count downstream is inflated and every average is wrong.

```sql
SELECT
    COUNT(*)                                AS total_rows,
    COUNT(DISTINCT sr_number)               AS distinct_sr_numbers,
    COUNT(*) - COUNT(DISTINCT sr_number)    AS excess_rows
FROM raw
```

```
 total_rows  distinct_sr_numbers  excess_rows
     517287               517287            0
```

## C03. Duplicate sr_number examples

*Why this matters:* If C02 shows excess rows, these are the ones to inspect. Duplicates are sometimes genuine revisions rather than errors, and that changes the fix.

```sql
SELECT sr_number, COUNT(*) AS occurrences
FROM raw
GROUP BY sr_number
HAVING COUNT(*) > 1
ORDER BY occurrences DESC, sr_number
LIMIT 10
```

```
Empty DataFrame
Columns: [sr_number, occurrences]
Index: []
```

## C04. Date coverage

*Why this matters:* Confirms the filter did what it claimed. Values outside the requested window mean the server-side filter did not behave as expected.

```sql
SELECT
    MIN(substr(date_created, 1, 10)) AS earliest_created,
    MAX(substr(date_created, 1, 10)) AS latest_created,
    SUM(CASE WHEN date_created IS NULL OR date_created = '' THEN 1 ELSE 0 END)
        AS blank_created
FROM raw
```

```
earliest_created latest_created  blank_created
      2023-01-01     2026-08-31            0.0
```

## C05. Monthly volume

*Why this matters:* Reveals gaps, partial months, and system changes. A month at half the usual volume is almost always a collection problem, not a real drop in demand, and analysing it as demand would be a serious error.

```sql
SELECT
    substr(date_created, 1, 7) AS month,
    COUNT(*)                   AS requests
FROM raw
WHERE date_created IS NOT NULL
GROUP BY month
ORDER BY month
```

```
  month  requests
2023-01      8850
2023-02      8361
2023-03      9270
2023-04      9795
2023-05     11128
2023-06     10106
2023-07     10589
2023-08     11062
2023-09     10424
2023-10     10273
2023-11      9437
2023-12      8497
2024-01     10866
2024-02      9809
2024-03      9678
2024-04     12490
2024-05     12850
2024-06     10452
2024-07     12589
2024-08     11343
2024-09      9975
2024-10     10098
2024-11      8167
2024-12      8499
2025-01     16534
2025-02     12226
2025-03     12271
2025-04     14126
2025-05     12965
2025-06     13192
2025-07     14556
2025-08     12896
2025-09     11445
2025-10     10860
2025-11      9614
2025-12     12244
2026-01     13665
2026-02     11949
2026-03     14680
2026-04     15760
2026-05     14085
2026-06     15531
2026-07     17881
2026-08     16199
```

## C06. Status distribution

*Why this matters:* Establishes how open and closed are represented, and whether sr_status_flag is a clean binary that can be trusted for the backlog definition.

```sql
SELECT
    sr_status_flag,
    sr_status,
    COUNT(*) AS requests
FROM raw
GROUP BY sr_status_flag, sr_status
ORDER BY requests DESC
LIMIT 30
```

```
sr_status_flag sr_status  requests
        CLOSED    CLOSED    403763
        CLOSED   CLOS-NO     38763
        CLOSED  ABAT-OWN     30615
        CLOSED  DUPLICAT     19157
          OPEN       NEW      7539
          OPEN   ORDERS1      5996
        CLOSED   CLOS-RI      3551
          OPEN   ORDERS2      2402
        CLOSED  CLOS-EXP      1872
          OPEN     CIVIL      1594
          OPEN  INPROGRS      1071
          OPEN  RESEARCH       330
          OPEN  DISPATCH       302
          OPEN  ACCEPTED       145
          OPEN     WDISP        45
          OPEN    SECURE        39
          OPEN  COMPLETE        29
          OPEN    APPEAL        29
          OPEN  CRIMINAL        20
          OPEN   ORDERS3        19
          OPEN   ORDERS4         3
          OPEN     ROUTE         1
        CLOSED  CLOS-EOY         1
           NaN      JUNK         1
```

## C07. SLA arithmetic: does date_created + planned_completion_days = planned_end_date?

*Why this matters:* This held on all five sample rows. If it holds across the full file, the completion deadline is a reliable published commitment and becomes the backbone of the on-time metric. If it does not, the exceptions need a rule.

```sql
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
```

```
 rows_testable  arithmetic_matches
        517214            517214.0
```

## C08. Deadline revisions

*Why this matters:* If the city revises deadlines often, measuring on-time against the revised date flatters performance. This decides whether the original deadline has to be the basis of the metric, and whether revision rate is itself a finding.

```sql
SELECT
    COUNT(*) AS total_rows,
    SUM(CASE WHEN date_revised_completion IS NOT NULL THEN 1 ELSE 0 END)
        AS revised_rows,
    ROUND(
        100.0 * SUM(CASE WHEN date_revised_completion IS NOT NULL THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0), 2) AS revised_pct
FROM raw
```

```
 total_rows  revised_rows  revised_pct
     517287        3843.0         0.74
```

## C09. Neighborhood columns: how often do they disagree?

*Why this matters:* Two geography columns exist and at least one sample row disagreed. Since the analysis compares neighborhoods, the wrong choice produces geography that does not reconcile against anything the city publishes.

```sql
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
```

```
 total_rows  neighborhood_blank  council_blank  disagreements
     517287                 0.0            0.0       120477.0
```

## C10. Impossible dates: closed before created

*Why this matters:* A record closed before it was created is a data error. The count tells you whether to exclude a handful of rows or investigate a systemic problem.

```sql
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
```

```
 closed_before_created  closed_same_day
                 232.0          61545.0
```

## C11. time_received format consistency

*Why this matters:* Time of day lives in a separate text column. Before reassembling it with the date in step 3, confirm every value follows one format. A single 24-hour value mixed into 12-hour values would shift results by 12 hours.

```sql
SELECT
    COUNT(*) AS total_rows,
    SUM(CASE WHEN time_received IS NULL THEN 1 ELSE 0 END) AS blank_time,
    SUM(CASE
            WHEN time_received IS NOT NULL
             AND NOT regexp_matches(time_received, '^[0-9]{1,2}:[0-9]{2} (AM|PM)$')
            THEN 1 ELSE 0
        END) AS unexpected_format
FROM raw
```

```
 total_rows  blank_time  unexpected_format
     517287        73.0              201.0
```

## C12. time_received unexpected-format examples

*Why this matters:* Shows the actual offending values, if C11 found any, so the parsing rule can handle them explicitly rather than by guesswork.

```sql
SELECT time_received, COUNT(*) AS occurrences
FROM raw
WHERE time_received IS NOT NULL
  AND NOT regexp_matches(time_received, '^[0-9]{1,2}:[0-9]{2} (AM|PM)$')
GROUP BY time_received
ORDER BY occurrences DESC
LIMIT 15
```

```
time_received  occurrences
        11:28            4
        11:08            4
        11:02            4
        11:33            4
        10:09            3
        12:29            3
        12:40            3
        11:32            3
        12:16            3
        13:10            3
        12:12            3
        12:25            3
        12:26            3
        10:50            3
        10:39            2
```

## C13. Censoring: open requests and overdue open requests

*Why this matters:* Open requests have no closure date, so they cannot be included in an average time-to-close without biasing it downward. Requests still within their deadline are not yet late and must not be counted as misses.

```sql
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
```

```
 total_rows  open_rows  no_close_date  open_and_past_deadline  open_and_not_yet_due
     517287    19564.0        19468.0                 13996.0                5442.0
```

## C14. Request type concentration

*Why this matters:* Shows whether a handful of types dominate volume. If they do, an overall on-time rate is really a weighted average of a few services, and the analysis has to segment rather than report one headline number.

```sql
SELECT
    sr_type_desc,
    COUNT(*)                                      AS requests,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM raw
GROUP BY sr_type_desc
ORDER BY requests DESC
LIMIT 20
```

```
                  sr_type_desc  requests  pct_of_total
METAL FURNITURE, SPEC COLLECTN     87715         16.96
      TRASH, BULK ITEM PICK-UP     29928          5.79
               POTHOLE, REPAIR     25997          5.03
         BUILDING, RESIDENTIAL     16782          3.24
 TRASH, REQUEST FOR COLLECTION     15520          3.00
TALL GRASS/WEEDS, PRIVATE PROP     14848          2.87
                311 ASSISTANCE     14693          2.84
      LITTER, PRIVATE PROPERTY     11226          2.17
      TRASH, MISSED COLLECTION     10017          1.94
                YARD WASTE,RTC      9153          1.77
  VEHICLE, ABANDONED IN STREET      8696          1.68
SIGNAL, TRAF/PED/SCHOOL REPAIR      8043          1.55
      TRASH CART, REGISTRATION      7775          1.50
     SLIPPERY STREETS, REQUEST      7745          1.50
       TRASH, IMPROPER SET OUT      7702          1.49
            SIGN, DOWN/MISSING      7476          1.45
      VEHICLE, OVERTIME PARKER      7431          1.44
     TIRES, SPECIAL COLLECTION      6310          1.22
 YARD WASTE, MISSED COLLECTION      6087          1.18
            TRASH CART, REPAIR      6018          1.16
```

## C15. Committed completion days by request type

*Why this matters:* The city promises 7 days for some services and 72 for others. This is the evidence that an unsegmented on-time rate would be misleading, and it shows whether a type's commitment has changed over time.

```sql
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
```

```
                  sr_type_desc  requests  distinct_commitments  min_days  max_days
METAL FURNITURE, SPEC COLLECTN     87715                    10      13.0      30.0
      TRASH, BULK ITEM PICK-UP     29928                    12      13.0     357.0
               POTHOLE, REPAIR     25997                    60      11.0     313.0
         BUILDING, RESIDENTIAL     16782                    82     363.0     970.0
 TRASH, REQUEST FOR COLLECTION     15520                    14       1.0      17.0
TALL GRASS/WEEDS, PRIVATE PROP     14848                   106      45.0     450.0
                311 ASSISTANCE     14693                     2       0.0       1.0
      LITTER, PRIVATE PROPERTY     11226                    12      45.0      90.0
      TRASH, MISSED COLLECTION     10017                    19       1.0      28.0
                YARD WASTE,RTC      9153                     9       6.0      14.0
  VEHICLE, ABANDONED IN STREET      8696                    20       1.0      57.0
SIGNAL, TRAF/PED/SCHOOL REPAIR      8043                    60       0.0     556.0
      TRASH CART, REGISTRATION      7775                    23       7.0      56.0
     SLIPPERY STREETS, REQUEST      7745                     6       1.0       6.0
       TRASH, IMPROPER SET OUT      7702                    17       1.0     164.0
            SIGN, DOWN/MISSING      7476                    55       1.0     352.0
      VEHICLE, OVERTIME PARKER      7431                    32       3.0     111.0
     TIRES, SPECIAL COLLECTION      6310                     7      14.0      26.0
 YARD WASTE, MISSED COLLECTION      6087                    19       6.0      29.0
            TRASH CART, REPAIR      6018                    27      17.0      67.0
```

## C16. Department distribution

*Why this matters:* Identifies the decision owners. A recommendation has to land on a named department, not on 'the city'.

```sql
SELECT
    dept_name,
    COUNT(*) AS requests,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM raw
GROUP BY dept_name
ORDER BY requests DESC
```

```
               dept_name  requests  pct_of_total
         PUBLIC SERVICES    315721         61.03
      CINC BUILDING DEPT     62624         12.11
   DEPT OF TRANS AND ENG     30014          5.80
   CITY MANAGER'S OFFICE     28260          5.46
        CINC HEALTH DEPT     19493          3.77
EMERGENCY COMMUNICATIONS     17553          3.39
       POLICE DEPARTMENT     14422          2.79
         PARK DEPARTMENT     10386          2.01
         CIN WATER WORKS      7519          1.45
   COMMUNITY DEVELOPMENT      6131          1.19
               FIRE DEPT      1642          0.32
   CINCINNATI RECREATION       989          0.19
REGIONAL COMPUTER CENTER       879          0.17
      METROPOLITAN SEWER       780          0.15
          LAW DEPARTMENT       586          0.11
     ENTERPRISE SERVICES       163          0.03
                     NaN        73          0.01
     TREASURY DEPARTMENT        42          0.01
          MAYOR'S OFFICE         7          0.00
            FINANCE DEPT         2          0.00
         HUMAN RESOURCES         1          0.00
```

## C18. Consistency: does the status flag agree with the presence of a close date?

*Why this matters:* C13 showed 19,564 requests flagged OPEN while 19,468 have no close date. The 96-row gap means one of the two fields is wrong on those rows, and the backlog definition has to say which field it trusts.

```sql
SELECT
    COALESCE(sr_status_flag, '(blank)') AS status_flag,
    CASE WHEN date_closed IS NULL THEN 'no close date' ELSE 'has close date' END
        AS close_date_present,
    COUNT(*) AS requests
FROM raw
GROUP BY status_flag, close_date_present
ORDER BY requests DESC
```

```
status_flag close_date_present  requests
     CLOSED     has close date    497702
       OPEN      no close date     19447
       OPEN     has close date       117
     CLOSED      no close date        20
    (blank)      no close date         1
```

## C19. Is the committed completion time a standard per service, or set per request?

*Why this matters:* C15 showed potholes carrying 60 different commitments between 11 and 313 days. If most requests of a type share one standard value, the outliers are exceptions to explain. If they do not, the commitment is set case by case and an on-time rate measured against it is close to meaningless.

```sql
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
```

```
                  sr_type_desc  priority  committed_days  requests  pct_of_type
                311 ASSISTANCE  STANDARD               1     14680         99.9
                311 ASSISTANCE  PRIORITY               1         7          0.0
                311 ASSISTANCE  STANDARD               0         5          0.0
         BUILDING, RESIDENTIAL  STANDARD             365     15884         94.6
         BUILDING, RESIDENTIAL  PRIORITY             365       246          1.5
         BUILDING, RESIDENTIAL HAZARDOUS             365       195          1.2
      LITTER, PRIVATE PROPERTY  STANDARD              45     11170         99.5
      LITTER, PRIVATE PROPERTY  STANDARD              46        28          0.2
      LITTER, PRIVATE PROPERTY  STANDARD              47        10          0.1
METAL FURNITURE, SPEC COLLECTN  STANDARD              14     78244         89.2
METAL FURNITURE, SPEC COLLECTN  STANDARD              30      9440         10.8
METAL FURNITURE, SPEC COLLECTN  STANDARD              15        11          0.0
               POTHOLE, REPAIR  STANDARD              12     25581         98.4
               POTHOLE, REPAIR  STANDARD              13       123          0.5
               POTHOLE, REPAIR HAZARDOUS              12        77          0.3
TALL GRASS/WEEDS, PRIVATE PROP  STANDARD              45     14102         95.0
TALL GRASS/WEEDS, PRIVATE PROP  STANDARD             450       236          1.6
TALL GRASS/WEEDS, PRIVATE PROP  STANDARD              46       141          0.9
      TRASH, BULK ITEM PICK-UP  STANDARD              14     23791         79.5
      TRASH, BULK ITEM PICK-UP  STANDARD              30      6117         20.4
      TRASH, BULK ITEM PICK-UP  STANDARD              15         4          0.0
 TRASH, REQUEST FOR COLLECTION  STANDARD               1     10044         64.7
 TRASH, REQUEST FOR COLLECTION  STANDARD               7      5334         34.4
 TRASH, REQUEST FOR COLLECTION  STANDARD               2        43          0.3
```

## C20. Has the committed completion time changed over the period?

*Why this matters:* C19 showed several services carry two standard commitments rather than one. If the city lengthened a commitment partway through the window, an improving on-time rate could reflect a looser promise rather than faster service. That distinction decides whether a trend is a finding or an artefact, so it has to be settled before any trend is reported.

```sql
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
```

```
                  sr_type_desc year  modal_days  modal_pct  distinct_values  requests_in_year
                311 ASSISTANCE 2023           1      100.0                2            5231.0
                311 ASSISTANCE 2024           1       99.9                2            4923.0
                311 ASSISTANCE 2025           1      100.0                1            3815.0
                311 ASSISTANCE 2026           1      100.0                1             724.0
         BUILDING, RESIDENTIAL 2023         365       97.7               21            4074.0
         BUILDING, RESIDENTIAL 2024         365       97.3               44            4586.0
         BUILDING, RESIDENTIAL 2025         365       96.7               41            4385.0
         BUILDING, RESIDENTIAL 2026         365       97.5               20            3737.0
      LITTER, PRIVATE PROPERTY 2023          45       98.6               12            3899.0
      LITTER, PRIVATE PROPERTY 2024          45      100.0                1            2477.0
      LITTER, PRIVATE PROPERTY 2025          45      100.0                1            3028.0
      LITTER, PRIVATE PROPERTY 2026          45      100.0                1            1822.0
METAL FURNITURE, SPEC COLLECTN 2023          14      100.0                9           28922.0
METAL FURNITURE, SPEC COLLECTN 2024          14       99.9                4           24958.0
METAL FURNITURE, SPEC COLLECTN 2025          14       72.4                2           19579.0
METAL FURNITURE, SPEC COLLECTN 2026          14       71.7                2           14256.0
               POTHOLE, REPAIR 2023          12       98.6               11            4086.0
               POTHOLE, REPAIR 2024          12       98.3               30            4686.0
               POTHOLE, REPAIR 2025          12       98.8               40           10338.0
               POTHOLE, REPAIR 2026          12       99.2               15            6887.0
TALL GRASS/WEEDS, PRIVATE PROP 2023          45       95.8               73            3782.0
TALL GRASS/WEEDS, PRIVATE PROP 2024          45       89.1               46            3084.0
TALL GRASS/WEEDS, PRIVATE PROP 2025          45       97.4               30            4178.0
TALL GRASS/WEEDS, PRIVATE PROP 2026          45       96.5               27            3804.0
      TRASH, BULK ITEM PICK-UP 2024          14      100.0                2            6433.0
      TRASH, BULK ITEM PICK-UP 2025          14       71.9                3           12675.0
      TRASH, BULK ITEM PICK-UP 2026          14       76.2               11           10820.0
 TRASH, REQUEST FOR COLLECTION 2023           7       81.1               12            5196.0
 TRASH, REQUEST FOR COLLECTION 2024           1       73.9               10            4629.0
 TRASH, REQUEST FOR COLLECTION 2025           1      100.0                1            3318.0
 TRASH, REQUEST FOR COLLECTION 2026           1      100.0                1            2377.0
```

## C17. Column completeness

*Why this matters:* a column that is 95 percent blank cannot support a metric, however useful it sounds. This decides which of the 70 columns enter the model in step 4.

```
                   column_name  blank_rows  blank_pct
           request_return_call    517287.0     100.00
date_revised_completion_reason    515814.0      99.72
         trash_recycle_cart_id    513849.0      99.34
       date_revised_completion    513444.0      99.26
        propty_city_dept_owner    506575.0      97.93
          propty_city_owned_yn    506575.0      97.93
               date_dispatched    505942.0      97.81
               time_dispatched    505942.0      97.81
                  structure_id    496061.0      95.90
                  bulky_item_5    494438.0      95.58
                      floor_id    493883.0      95.48
                       unit_id    492648.0      95.24
              street_direction    485784.0      93.91
                  bulky_item_4    483376.0      93.44
                  bulky_item_3    467695.0      90.41
                  bulky_item_2    442786.0      85.60
                  bulky_item_1    396397.0      76.63
       collection_special_date    393262.0      76.02
           ham_pave_polygon_id    302727.0      58.52
                 dept_division    182050.0      35.19
              collection_route    156022.0      30.16
               collection_dist    155357.0      30.03
                collection_day     42833.0       8.28
                segidusng_xref     39695.0       7.67
                   date_closed     19468.0       3.76
               police_district      2182.0       0.42
                    munitwnshp      1059.0       0.20
                       zipcode       960.0       0.19
                       address       270.0       0.05
                       city_id       270.0       0.05
                   street_name       270.0       0.05
                     street_no       270.0       0.05
                      location       121.0       0.02
               method_received        89.0       0.02
                      priority        78.0       0.02
              date_last_update        30.0       0.01
            date_status_change        30.0       0.01
                     dept_code        73.0       0.01
                     dept_name        73.0       0.01
                    group_desc        73.0       0.01
                   group_title        75.0       0.01
             nearest_parcel_no        30.0       0.01
                     num_tires        42.0       0.01
       planned_completion_days        73.0       0.01
              planned_end_date        73.0       0.01
         planned_response_time        73.0       0.01
                  sr_type_desc        73.0       0.01
              time_last_update        30.0       0.01
                 time_received        73.0       0.01
            time_status_change        30.0       0.01
                transfer_allow        70.0       0.01
                     ROW_COUNT    517287.0       0.00
community_council_neighborhood         0.0       0.00
                  date_created         0.0       0.00
            date_time_received         0.0       0.00
                      group_id         0.0       0.00
                      latitude        17.0       0.00
                     longitude        17.0       0.00
                  neighborhood         0.0       0.00
               num_bulky_items         6.0       0.00
                    num_freons         8.0       0.00
                  num_potholes         0.0       0.00
                  num_sofabeds         8.0       0.00
planned_hours_tostart_response         0.0       0.00
               police_rpt_area         0.0       0.00
                     sr_number         0.0       0.00
                     sr_status         0.0       0.00
                sr_status_flag         1.0       0.00
                       sr_type         0.0       0.00
          transfered_num_times         0.0       0.00
                       user_id         0.0       0.00
```
