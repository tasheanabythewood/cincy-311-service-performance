# Source definitions: documented versus observed

Reconciles the City of Cincinnati's published CSR data dictionary against what
the snapshot actually contains. Every metric defined in step 3 cites this file
for its source definition, and every place where the data disagrees with the
documentation is recorded here rather than resolved silently.

- Source document: Citizen Service Requests (CSRs) Data Dictionary, City of
  Cincinnati, Office of Performance and Data Analytics
- Snapshot tested: `service_requests__2026-09-18.csv.gz`, 517,287 rows
- Reconciled: 2026-09-18

---

## 1. Confirmed by the publisher

| Item | Publisher states | Our check | Status |
| --- | --- | --- | --- |
| Unique identifier | `SR_NUMBER` | C02 found 517,287 distinct values across 517,287 rows | Verified. Grain is one row per service request. |
| `SR_STATUS_FLAG` | Whether the request is open or closed | C06 returned OPEN, CLOSED, and one blank | Verified as a binary, with one exception to handle. |

---

## 2. Conflict: `PLANNED_COMPLETION_DAYS`

**The publisher defines it as** the projected days to complete the request
"from start of response".

**The data behaves differently.** `PLANNED_END_DATE` equals `DATE_CREATED`
plus `PLANNED_COMPLETION_DAYS`, not `PLANNED_RESPONSE_TIME` plus
`PLANNED_COMPLETION_DAYS`.

Evidence:

- Tested on 5 sample rows: the from-creation reading matched 5 of 5, the
  from-response reading matched 0 of 5.
- Tested on the full file (check C07): the from-creation reading held on
  517,214 of 517,214 testable rows. No exceptions.

**Resolution.** Treat the commitment clock as starting at submission, which is
what the data does on every row. Record the documentation conflict as a stated
limitation rather than choosing the documented reading over the evidence.

**Why this matters to a resident.** Under the documented reading, the clock
would not start until the city began work, so a request sitting untouched
would never become late. Under the observed reading, the clock starts when the
request is submitted, which is what a resident experiences. The observed
reading is both what the data supports and the more meaningful measure.

---

## 3. Unresolved: two neighborhood fields

The publisher documents `NEIGHBORHOOD` only as the neighborhood of the service
request, naming no boundary system. `COMMUNITY_COUNCIL_NEIGHBORHOOD` is not in
the dictionary at all.

Check C09 found the two fields disagree on 120,477 rows, 23.3 percent, with no
blanks in either.

**Resolution.** Use `NEIGHBORHOOD` as the analytical geography, because it is
the field the publisher documents. State the 23.3 percent disagreement as a
limitation, and do not mix the two in any single analysis.

**Open question.** Whether the disagreement reflects two legitimate boundary
systems or an error is not established by the dictionary. Confidence: low.
Resolving it requires a boundary reference the city has not published here.

---

## 4. Undocumented columns

Six of the 70 columns in the snapshot do not appear in the dictionary:

| Column | Notes |
| --- | --- |
| `community_council_neighborhood` | See section 3. |
| `latitude`, `longitude` | No statement of precision or whether coordinates are offset for privacy. |
| `date_time_received` | Renders without a time component, so it appears to be text rather than a timestamp. |
| `segidusng_xref` | Purpose unknown. |
| `ham_pave_polygon_id` | Purpose unknown. 58.5 percent blank. |

No documented column is missing from the data.

**Resolution.** Undocumented fields may be used for description but not as the
basis of a headline metric, and any use must say the field is undocumented.

---

## 5. Defined in name only

The dictionary gives no value list for `SR_STATUS`, and the data contains 24
distinct values including `DUPLICAT`, `ABAT-OWN`, `CLOS-NO`, `CLOS-RI`,
`CLOS-EXP`, `CLOS-EOY`, and `ORDERS1` through `ORDERS4`.

`TRANSFER_ALLOW` and `TRANSFERED_NUM_TIMES` appear in the dictionary with no
description.

**Resolution.** Any reading of these codes is inference from the label, not a
published definition. Where a metric depends on one, label it an assumption and
test how sensitive the result is to that assumption.

---

## 6. Time of day is not fully available

The dictionary describes `DATE_CREATED` and `DATE_CLOSED` as holding date and
time. In the snapshot both carry a zeroed time component.

`TIME_RECEIVED` supplies submission time separately. There is no corresponding
closure time column.

**Resolution.** Measure completion in whole days. This is sound, because the
commitment itself is expressed in whole days.

---

## 7. Response timeliness cannot be measured

`DATE_DISPATCHED` is documented as the actual date response began. It is blank
on 97.8 percent of rows (check C17).

**Resolution.** The response commitment
(`PLANNED_HOURS_TOSTART_RESPONSE`, `PLANNED_RESPONSE_TIME`) is out of scope.
There is no usable actual to compare it against. State this in the case study
rather than quietly omitting it: a reader may reasonably expect response time
to be covered.
