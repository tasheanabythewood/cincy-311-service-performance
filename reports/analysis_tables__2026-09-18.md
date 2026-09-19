# Analysis tables

- Warehouse: `warehouse.duckdb`
- As-of date: 2026-09-18
- Every rate is SUM(numerator) / SUM(denominator), never an average of percentages.
- On-time trends cover the four stable-commitment services only. See `reports/metric_dictionary.md` section 5.
- 2026 covers January to August only.

## A0. Integrity: is the service code one-to-one with its description?

*Why:* dim_service holds 695 service types. If a single sr_type maps to more than one description, grouping by code and grouping by description give different answers, and any chart built on one of them is arguable.

```sql
SELECT
    COUNT(*)                        AS rows_in_dim,
    COUNT(DISTINCT sr_type)         AS distinct_codes,
    COUNT(DISTINCT sr_type_desc)    AS distinct_descriptions
FROM dim_service
WHERE service_key <> -1
```

```
 rows_in_dim  distinct_codes  distinct_descriptions
         695             524                    654
```

## A0b. Service codes carrying more than one description

*Why:* Lists the offenders, if A0 found any. A code whose description changed over time is a slowly changing dimension, and the analysis has to pick one representation and say so.

```sql
SELECT sr_type, COUNT(*) AS descriptions, MIN(sr_type_desc) AS example_a,
       MAX(sr_type_desc) AS example_b
FROM dim_service
WHERE service_key <> -1
GROUP BY sr_type
HAVING COUNT(*) > 1
ORDER BY descriptions DESC, sr_type
LIMIT 10
```

```
 sr_type  descriptions                              example_a                             example_b
CMDVABDV             5             VEHICLE, ABANDONED PARKING   VEHICLE, PARKED >24 HOURS ON STREET
DFLTPARK             4 ABANDONED VEHICLE, ON PRIVATE PROPERTY              WATER MAIN, LEAKS/BREAKS
ILLHOMEC             4                    HOMELESS ENCAMPMENT          REPORT A HOMELESS ENCAMPMENT
 MTL-FRN             4         METAL FURNITURE, SPEC COLLECTN TRASH, SCHEDULE PICK-UP OF BULKY ITEM
PLCJUNKV             4  VEHICLE, ABANDONED DISABLED ON STREET                VEHICLE, ROW JUNK/ABAN
RF-COLLT             4               TRASH, MISSED COLLECTION         TRASH, REQUEST FOR COLLECTION
 SGNVRHD             4                  SIGN, OVERHEAD REPAIR  TRAFFIC SIGNAL, OVERHEAD SIGN REPAIR
  SLPYST             4                     ICY, SNOWY STREETS             SLIPPERY STREETS, REQUEST
STRTLITE             4                          LIGHT, REPAIR                   STREETLIGHT, REPAIR
TTRMPVUF             4          TREE, PRUNE REQD, ROW PRIVATE            TREE, TRIM REQUIRD PRIVATE
```

## A0c. Codes behind the nine services in scope, with their date spans

*Why:* A0b showed MTL-FRN carrying both a metal-furniture description and a bulky-item one, and RF-COLLT carrying both trash collection descriptions. If those are the same code relabelled over time, then the volume 'migration' reported from check C20 is a rename, not a reclassification, and that finding has to be withdrawn. Date spans settle it: a rename gives consecutive, non-overlapping spans.

```sql
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
```

```
 sr_type                          sr_type_desc  requests first_seen  last_seen  modal_days
311ASSIT                        311 ASSISTANCE   14693.0 2023-08-25 2026-08-04           1
311ASSIT                                   NaN       1.0 2024-09-27 2024-09-27        <NA>
 BLD-RES                 BUILDING, RESIDENTIAL   16782.0 2023-01-01 2026-08-31         365
 BLD-RES                                   NaN       2.0 2024-02-09 2024-11-12        <NA>
LITR-PRV              LITTER, PRIVATE PROPERTY   11226.0 2023-01-01 2026-08-31          45
LITR-PRV             LITTER,  PRIVATE PROPERTY    4598.0 2023-05-10 2026-08-31          45
LITR-PRV                                   NaN       1.0 2023-11-18 2023-11-18        <NA>
 MTL-FRN        METAL FURNITURE, SPEC COLLECTN   87715.0 2023-01-01 2026-08-31          14
 MTL-FRN                                   NaN      24.0 2024-01-07 2026-06-19        <NA>
 MTL-FRN              TRASH, BULK ITEM PICK-UP   29928.0 2024-07-12 2026-08-31          14
 MTL-FRN TRASH, SCHEDULE PICK-UP OF BULKY ITEM       3.0 2026-01-06 2026-01-22          30
  PTHOLE                       POTHOLE, REPAIR   25997.0 2023-01-01 2026-08-31          12
  PTHOLE                                   NaN       6.0 2023-10-24 2026-04-05        <NA>
  PTHOLE                        POTHOLE REPAIR      24.0 2025-04-10 2026-01-09          12
RF-COLLT         TRASH, REQUEST FOR COLLECTION   15520.0 2023-01-02 2026-08-31           1
RF-COLLT          TRASH, MISSED FOR COLLECTION       1.0 2024-07-22 2024-07-22           1
RF-COLLT              TRASH, MISSED COLLECTION   10017.0 2024-07-22 2026-08-31           1
RF-COLLT                                   NaN       3.0 2025-12-03 2026-02-07        <NA>
TLGR-PRV        TALL GRASS/WEEDS, PRIVATE PROP   14848.0 2023-01-01 2026-08-31          45
TLGR-PRV                                   NaN       1.0 2023-08-31 2023-08-31        <NA>
```

## A0d. Across all multi-description codes: rename or concurrent variants?

*Why:* Sizes the problem. Sequential spans mean the description was changed and the service is continuous, so grouping by description splits one service into several across time. Overlapping spans mean genuinely distinct sub-services sharing a code, which is the opposite problem.

```sql
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
```

```
                                  pattern  codes  requests  pct_of_all
      concurrent: variants share one code     65  326221.0        63.1
sequential: description changed over time     46   12830.0         2.5
```

## A1. Demand and outcomes by year, all services

*Why:* Context for everything else. Demand rose steadily across the window, so a flat on-time rate would represent more work delivered at the same standard, not standing still.

```sql
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
```

```
 year   intake  duplicates  duplicate_pct  evaluable  on_time_pct  open_overdue
 2023 117792.0      4547.0            3.9   113216.0         75.0        2165.0
 2024 126816.0      4045.0            3.2   122719.0         76.7        2806.0
 2025 152929.0      6087.0            4.0   145947.0         63.2        3192.0
 2026 119750.0      4452.0            3.7   110527.0         77.7        5833.0
```

## A2. On-time trend, stable-commitment services only

*Why:* The headline trend. Restricted to the four services whose committed completion time held steady across the window, so a change here is performance rather than a moving promise. 2026 covers January to August only.

```sql
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
```

```
 year  intake  mature_evaluable  pct_mature  on_time_pct  closed_late  never_closed  services_present
 2023 16599.0           14391.0        86.7         74.2       2779.0         941.0                 4
 2024 16441.0           14371.0        87.4         81.2       1349.0        1347.0                 4
 2025 23203.0           18803.0        81.0         83.5       1957.0        1145.0                 4
 2026 17242.0           10878.0        63.1         95.1        489.0          43.0                 3
```

## A3. On-time trend by service and year

*Why:* Where the movement in A2 comes from. A citywide figure can hide one service improving while another collapses.

```sql
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
```

```
 sr_type  days  year  intake  mature_evaluable  pct_mature  on_time_pct  never_closed
 BLD-RES   365  2023  4074.0            3664.0        89.9         44.8         935.0
 BLD-RES   365  2024  4586.0            4187.0        91.3         64.1        1321.0
 BLD-RES   365  2025  4385.0            2859.0        65.2         59.0        1133.0
 BLD-RES   365  2026  3737.0               0.0         0.0          NaN           0.0
LITR-PRV    45  2023  4654.0            3916.0        84.1         81.7           0.0
LITR-PRV    45  2024  4083.0            3552.0        87.0         83.9          16.0
LITR-PRV    45  2025  4275.0            3651.0        85.4         84.2           4.0
LITR-PRV    45  2026  2812.0            2023.0        71.9         92.0          14.0
  PTHOLE    12  2023  4086.0            3768.0        92.2         94.5           0.0
  PTHOLE    12  2024  4686.0            4128.0        88.1         94.2           0.0
  PTHOLE    12  2025 10361.0            8999.0        86.9         91.0           0.0
  PTHOLE    12  2026  6888.0            6357.0        92.3         96.6           0.0
TLGR-PRV    45  2023  3782.0            3043.0        80.5         74.5           6.0
TLGR-PRV    45  2024  3084.0            2504.0        81.2         84.8          10.0
TLGR-PRV    45  2025  4178.0            3294.0        78.8         83.4           8.0
TLGR-PRV    45  2026  3804.0            2498.0        65.7         93.9          29.0
```

## A9. Which services caused the 2025 citywide drop?

*Why:* A1 shows the all-service on-time rate falling 13.5 points in 2025 and recovering in 2026, while A2 shows the four stable services rising every year. The drop is therefore entirely outside the stable set. This ranks services by their contribution to it, weighting the rate change by volume so that a large service moving a little outranks a tiny one collapsing.

```sql
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
```

```
                 service_label  eval_2024  pct_2024  eval_2025  pct_2025  change_pts  shortfall
METAL FURNITURE, SPEC COLLECTN    31347.0      85.2    32156.0      56.8       -28.4     9130.0
 TRASH, REQUEST FOR COLLECTION     6382.0      32.0     7456.0      20.0       -12.0      891.0
            SIGN, DOWN/MISSING     1380.0      34.1     2382.0      11.3       -22.8      542.0
      TRASH CART, REGISTRATION     2023.0      97.0     2090.0      78.9       -18.1      378.0
   ROW FURNITURE/TRASH DUMPING     2387.0      83.5     3268.0      73.0       -10.5      343.0
       TRASH, IMPROPER SET OUT     1401.0      60.3     2375.0      46.2       -14.1      334.0
               POTHOLE, REPAIR     4128.0      94.2     8999.0      91.0        -3.2      286.0
 TALL GRASS/WEEDS, PS PROPERTY      652.0      87.4      681.0      45.7       -41.8      284.0
             GRAFFITI, REMOVAL      746.0      74.8      518.0      38.8       -36.0      186.0
                YARD WASTE,RTC     3809.0      89.8     3394.0      85.1        -4.7      160.0
  RECYCLING, REPAIR/REPLACE 96     1099.0      99.7     1639.0      90.5        -9.2      151.0
 RECYCLING, COLLECT GREEN CART     1869.0      93.1     2466.0      87.1        -6.0      149.0
 RECYCLING, NEW 96 GALLON CART      962.0      87.1     1020.0      72.8       -14.3      146.0
         BUILDING, RESIDENTIAL     4187.0      64.1     2859.0      59.0        -5.0      143.0
     TIRES, SPECIAL COLLECTION     1770.0      92.4     1597.0      83.8        -8.6      137.0
```

## A10. MTL-FRN decomposed: is the 2025 drop real service degradation?

*Why:* MTL-FRN is 117,670 requests, 22.7 percent of the file, and accounts for 69 percent of the 2025 citywide shortfall. Its on-time rate fell 28.4 points on flat volume. A LONGER commitment appeared in 2025, which should have raised the rate, not cut it. Splitting by commitment tier and by label separates two possibilities: the service genuinely degraded, or a slower sub-service arrived carrying its own label and its own commitment.

```sql
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
```

```
 year                  service_label  committed_days  intake  mature_evaluable  on_time_pct  median_days
 2023 METAL FURNITURE, SPEC COLLECTN              14 28908.0           28864.0         81.0          9.0
 2024 METAL FURNITURE, SPEC COLLECTN              14 24945.0           24904.0         88.1          8.0
 2024       TRASH, BULK ITEM PICK-UP              14  6432.0            6429.0         74.0         11.0
 2025 METAL FURNITURE, SPEC COLLECTN              14 14168.0           14109.0         41.7         17.0
 2025 METAL FURNITURE, SPEC COLLECTN              30  5411.0            5385.0         96.2          8.0
 2025       TRASH, BULK ITEM PICK-UP              14  9113.0            9101.0         41.3         17.0
 2025       TRASH, BULK ITEM PICK-UP              30  3561.0            3560.0         96.4         11.0
 2026 METAL FURNITURE, SPEC COLLECTN              14 10227.0           10154.0         85.5          7.0
 2026 METAL FURNITURE, SPEC COLLECTN              30  4029.0            4016.0         97.1          4.0
 2026       TRASH, BULK ITEM PICK-UP              14  8248.0            8234.0         85.4          7.0
 2026       TRASH, BULK ITEM PICK-UP              30  2556.0            2554.0         97.9          5.0
```

## A11. MTL-FRN month by month: step change or gradual slide?

*Why:* A sudden drop in one month points at a policy, system or contract change. A gradual slide points at capacity falling behind. The shape of the decline decides which recommendation is even plausible.

```sql
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
```

```
year_month  intake  mature_evaluable  on_time_pct  median_days  pct_on_30day
   2024-01  2163.0            2161.0         96.1          5.0           0.0
   2024-02  2300.0            2297.0         97.3          5.0           0.0
   2024-03  2701.0            2699.0         97.9          6.0           0.0
   2024-04  2897.0            2892.0         97.4          5.0           0.0
   2024-05  3057.0            3050.0         97.6          7.0           0.0
   2024-06  2673.0            2669.0         89.2         11.0           0.0
   2024-07  3299.0            3293.0         62.8         14.0           0.0
   2024-08  2650.0            2646.0         36.6         15.0           0.0
   2024-09  2472.0            2463.0         71.3         13.0           0.0
   2024-10  2586.0            2581.0         93.0         10.0           0.0
   2024-11  2277.0            2274.0         94.3          8.0           0.0
   2024-12  2328.0            2322.0         95.9          6.0           0.0
   2025-01  1867.0            1861.0         86.6          5.0           0.0
   2025-02  2264.0            2255.0         65.4          7.0           0.0
   2025-03  3183.0            3176.0         63.1         11.0           0.0
   2025-04  3055.0            3047.0         64.3         13.0           0.0
   2025-05  2929.0            2921.0         57.1         14.0           0.0
   2025-06  3047.0            3034.0         14.9         18.5           0.0
   2025-07  3257.0            3249.0          8.5         21.0           0.0
   2025-08  2876.0            2865.0          5.1         24.0           0.0
   2025-09  2542.0            2522.0         69.9         22.0          68.0
   2025-10  2532.0            2529.0         99.8         12.0         100.0
   2025-11  2390.0            2380.0         91.8          6.0         100.0
   2025-12  2322.0            2317.0         94.6          5.0         100.0
   2026-01  2203.0            2200.0         95.6          5.0          99.9
   2026-02  2174.0            2167.0         99.7          4.0         100.0
   2026-03  3584.0            3575.0         97.3          4.0          61.8
   2026-04  3345.0            3334.0         95.7          5.0           0.0
   2026-05  3179.0            3171.0         91.8          5.0           0.0
   2026-06  3571.0            3541.0         89.8          7.0           0.0
   2026-07  3942.0            3917.0         76.2         11.0           0.0
   2026-08  3083.0            3072.0         68.8         12.0           0.0
```

## A4. The overdue backlog, by age band and service

*Why:* How stale the backlog is, across all services. A request a month past its date and one three years past it are both misses, but only one of them is plausibly still live work.

```sql
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
HAVING SUM(f.open_overdue_count) >= 150
ORDER BY overdue DESC
LIMIT 20
```

```
 sr_type                  service_label  overdue  within_90d  d91_365  d1_2yr  over_2yr  median_days_overdue
 BLD-RES          BUILDING, RESIDENTIAL   3389.0       439.0   1021.0  1291.0     638.0                420.0
 MTL-FRN METAL FURNITURE, SPEC COLLECTN   1527.0      1175.0    352.0     0.0       0.0                 58.0
BLD_VACR  BUILDING, VACANT AND OPEN RES   1030.0       111.0    332.0   347.0     240.0                413.5
CMDVABDV       VEHICLE, OVERTIME PARKER    583.0       336.0    224.0    23.0       0.0                 76.0
CAG_PPDV   CAGIS PERMITS PLUS, DEV WORK    439.0        22.0     85.0   202.0     130.0                661.0
 BLD-COM  BUILDING, COMMERCIAL CBHCODEC    414.0        23.0    102.0   120.0     169.0                612.5
BLDFRESC     BUILDING, FIRE ESCAPE INSP    388.0         0.0      0.0   232.0     156.0                680.5
 ZONCCER   ZONING, CODE ENFORCEMENT RES    370.0        70.0    154.0   122.0      24.0                266.5
BLDFRFAC   BUILDING, FACADE/FIRE ESCAPE    327.0        98.0     87.0    67.0      75.0                288.0
  TREEPR TREE, DEAD ON PRIV PROP STNDRD    260.0        72.0     77.0    63.0      48.0                334.5
DASTRAST            DISASTER ASSISTANCE    236.0       236.0      0.0     0.0       0.0                 42.0
 SIDWLKH           SIDEWALK, REPAIR HAZ    222.0         9.0     69.0   144.0       0.0                426.0
TRSHCITE         TRASH, CITATION ISSUED    204.0       163.0     41.0     0.0       0.0                 57.0
SVCCMPLT       SERVICE COMPLAINT, TRASH    195.0       189.0      6.0     0.0       0.0                 36.0
CRNCAN-D            CORNER CAN, DAMAGED    169.0       119.0     50.0     0.0       0.0                 72.0
   PAVMK       PAVEMENT MARKINGS, FADED    159.0        53.0     95.0    11.0       0.0                119.0
RCNEWLIC    RESTAURANT CONSULT, NEW LIC    157.0        26.0     53.0    54.0      24.0                350.0
CFDANNUL    FIRE, ANNUAL INSPECTION REQ    156.0       103.0     52.0     1.0       0.0                 65.0
```

## A5. The overdue backlog by department

*Why:* A recommendation has to land on a named decision owner. This says which department would have to act.

```sql
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
```

```
               dept_name   intake  overdue  pct_of_own_intake  pct_of_all_overdue  on_time_pct
      CINC BUILDING DEPT  62624.0   7201.0               11.5                51.5         71.8
         PUBLIC SERVICES 315721.0   4220.0                1.3                30.2         70.0
   DEPT OF TRANS AND ENG  30014.0    549.0                1.8                 3.9         79.5
REGIONAL COMPUTER CENTER    879.0    450.0               51.2                 3.2         37.3
   COMMUNITY DEVELOPMENT   6131.0    375.0                6.1                 2.7         13.5
        CINC HEALTH DEPT  19493.0    351.0                1.8                 2.5         89.2
               FIRE DEPT   1642.0    338.0               20.6                 2.4         31.4
       POLICE DEPARTMENT  14422.0    217.0                1.5                 1.6         43.7
   CITY MANAGER'S OFFICE  28260.0    171.0                0.6                 1.2         90.3
     TREASURY DEPARTMENT     42.0     40.0               95.2                 0.3          4.8
      METROPOLITAN SEWER    780.0     36.0                4.6                 0.3         36.6
         PARK DEPARTMENT  10386.0     23.0                0.2                 0.2         90.3
          LAW DEPARTMENT    586.0     12.0                2.0                 0.1         97.9
          MAYOR'S OFFICE      7.0      7.0              100.0                 0.1          0.0
         CIN WATER WORKS   7519.0      3.0                0.0                 0.0         76.1
```

## A6. Pothole repair on-time rate by neighbourhood

*Why:* Neighbourhood comparison, holding service mix constant by restricting to ONE service with a stable 12-day commitment. Comparing neighbourhoods across a mixed basket of services would confound where requests come from with how fast they are handled, which is the single easiest way to turn an operational finding into an unfounded claim about fairness.

```sql
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
HAVING SUM(f.evaluable_count) >= 150
ORDER BY on_time_pct
```

```
                  neighborhood  evaluable  on_time_pct  median_days
NORTH AVONDALE - PADDOCK HILLS      329.0         85.7          3.0
                    CORRYVILLE      446.0         88.3          3.0
                PLEASANT RIDGE      558.0         88.9          3.0
                       LINWOOD      520.0         89.6          3.0
                    QUEENSGATE      657.0         89.6          2.0
                           CUF      731.0         90.0          2.0
                      MT. AIRY      633.0         90.0          3.0
             EAST WALNUT HILLS      197.0         90.4          3.0
               KENNEDY HEIGHTS      222.0         91.0          3.0
                        OAKLEY     1521.0         91.3          3.0
                      HARTWELL      241.0         91.3          3.0
              LOWER PRICE HILL      188.0         92.0          2.0
                       CLIFTON      535.0         92.1          3.0
                      WEST END      450.0         92.2          2.0
             COLUMBIA TUSCULUM      176.0         92.6          3.0
                   MT. LOOKOUT      253.0         92.9          3.0
                     NORTHSIDE      446.0         93.0          2.0
                     RIVERSIDE      230.0         93.0          3.0
                     MT. ADAMS      217.0         93.1          3.0
                     PENDLETON      165.0         93.3          3.0
                      CARTHAGE      183.0         93.4          2.0
                  WINTON HILLS      220.0         93.6          2.0
                  WALNUT HILLS      834.0         93.8          2.0
                      DOWNTOWN      776.0         94.1          2.0
                      EVANSTON      479.0         94.2          3.0
                      AVONDALE      586.0         94.4          2.0
                    MT. AUBURN      246.0         94.7          2.0
                  MADISONVILLE      827.0         94.9          2.0
                OVER-THE-RHINE      262.0         95.0          2.0
                      EAST END      278.0         95.0          2.0
                      ROSELAWN      643.0         95.2          3.0
                   SAYLER PARK      440.0         95.2          2.0
               CAMP WASHINGTON      377.0         95.2          1.0
                     HYDE PARK     1031.0         95.3          2.0
               WEST PRICE HILL      944.0         95.4          2.0
          SPRING GROVE VILLAGE      268.0         95.9          2.0
                     BOND HILL      502.0         96.2          2.0
               EAST PRICE HILL      811.0         96.5          2.0
                    CALIFORNIA      180.0         96.7          2.0
                MT. WASHINGTON      726.0         97.1          2.0
                      WESTWOOD     2071.0         97.2          2.0
                  COLLEGE HILL     1177.0         97.6          2.0
```

## A7. Duplicate rate by service

*Why:* Duplicates are intake cost with no service delivered. A high rate points at a reporting experience that does not tell a resident the problem is already known, which is a cheaper thing to fix than crew capacity.

```sql
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
HAVING SUM(f.request_count) >= 1500
ORDER BY duplicate_pct DESC
LIMIT 15
```

```
 sr_type                  service_label  intake  duplicates  duplicate_pct
TLGR-PRV TALL GRASS/WEEDS, PRIVATE PROP 14849.0      2931.0           19.7
ADASDWKO         SIDEWALK, OBSTRUCTIONS  1901.0       308.0           16.2
DUMP-PVS  DUMPING, PRV PROP <2500 SQ FT  2072.0       333.0           16.1
BLD_VACR  BUILDING, VACANT AND OPEN RES  1909.0       302.0           15.8
LITR-PRV       LITTER, PRIVATE PROPERTY 15825.0      2369.0           15.0
CMDVABDV       VEHICLE, OVERTIME PARKER  8174.0      1003.0           12.3
  PTHOLE                POTHOLE, REPAIR 26027.0      2734.0           10.5
  STRSGN             SIGN, DOWN/MISSING  7477.0       754.0           10.1
MSSNGSTR  SIGN, STREET SIGN NAME ISSUES  1596.0       159.0           10.0
 ZONCCER   ZONING, CODE ENFORCEMENT RES  2526.0       218.0            8.6
 BLD-COM  BUILDING, COMMERCIAL CBHCODEC  2041.0       171.0            8.4
 SIDWLKH           SIDEWALK, REPAIR HAZ  2000.0       166.0            8.3
 BLD-RES          BUILDING, RESIDENTIAL 16784.0      1393.0            8.3
  SGNDNA   SIGN, DOWN/MISSING STOP SIGN  1598.0       118.0            7.4
TSIG-MAL SIGNAL, TRAF/PED/SCHOOL REPAIR  8043.0       582.0            7.2
```

## A8. Intake channel and outcome, stable-commitment services

*Why:* Whether how a request arrives is associated with how it ends. Any difference here is an association, not a cause: channels are chosen by different people reporting different problems.

```sql
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
```

```
          method_received  intake  duplicate_pct  evaluable  on_time_pct
                 INTERNET 47574.0           13.7    39275.0         82.0
                 311 CALL 16213.0           14.4    13358.0         88.6
                    PHONE  4193.0           10.5     3700.0         80.8
                    RADIO  2339.0            0.9     2300.0         99.4
                INSPECTOR  1953.0            2.4     1907.0         67.0
                     CHAT   640.0            6.6      573.0         92.1
            TROD EMPLOYEE   275.0            0.0      275.0         98.2
                    EMAIL   233.0            8.6      213.0         85.4
                  CSR_API    25.0           24.0       19.0         52.6
             (not stated)    11.0            0.0        1.0        100.0
             SOCIAL MEDIA     8.0            0.0        8.0        100.0
    EMERGENCY SERVICE REP     6.0            0.0        6.0        100.0
             NOD GRAFFITI     4.0           25.0        3.0        100.0
          CITY DEPARTMENT     3.0            0.0        3.0        100.0
                    MAYOR     2.0            0.0        2.0        100.0
                  WALK IN     2.0            0.0        2.0        100.0
                     MAIL     1.0            0.0        1.0          0.0
CUSTOMER SERVICE RESPONSE     1.0          100.0        0.0          NaN
        COMMUNITY COUNCIL     1.0            0.0        1.0          0.0
           NOD MANAGEMENT     1.0            0.0        1.0        100.0
```
