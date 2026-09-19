# Metric dictionary

Locked 2026-09-18, before any number was produced.

The executable version of every definition here is `src/definitions.py`. If the
two ever disagree, the code wins, because the code is what runs. Source field
definitions and the places where the publisher's documentation conflicts with
the data are recorded in `reports/source_definitions.md`.

- Snapshot: `service_requests__2026-09-18.csv.gz`, 517,287 requests
- Window: requests created 2023-01-01 through 2026-08-31
- As-of date for all open-request measures: **2026-09-18**, the snapshot date

---

## 1. The as-of date is pinned, not current

Whether an open request counts as overdue depends on the date you ask. Every
measure involving an open request uses 2026-09-18, taken from the snapshot
manifest.

Using the current date instead would mean an identical input file produces
different answers in March, and no figure in the case study could be
reproduced. Pinning makes every number a statement about a specific moment.

---

## 2. Populations

Three populations, used for different questions. Mixing them is the most likely
way to produce two numbers that disagree.

| Population | Definition | Answers |
| --- | --- | --- |
| **Intake** | All 517,287 requests, duplicates included | How much demand reaches 311 |
| **Service** | Intake minus requests closed as `DUPLICAT` | How much independent work exists |
| **Evaluable** | Requests whose timeliness outcome is known as of the snapshot date | Denominator of the on-time rate |

### Why duplicates leave the service population

A duplicate is not an independent unit of work. Counting it inflates both
demand and the on-time rate, since duplicates are likely to close quickly.

It remains in the intake population, because someone did contact the city and
the call centre did handle it. The duplicate rate is reported as a finding in
its own right, as an intake-efficiency measure.

---

## 3. Outcome classification

Every request falls into exactly one bucket. The order of tests matters: data
quality first, then duplicates, then timeliness.

| Bucket | Condition |
| --- | --- |
| `excluded: no commitment recorded` | No creation date or no committed completion date |
| `excluded: closed before created` | Closure date earlier than creation date |
| `excluded: duplicate request` | Status is `DUPLICAT` |
| `on time` | Closed on or before the committed completion date |
| `late` | Closed after the committed completion date |
| `open, overdue` | Not closed, and the committed date has passed |
| `open, not yet due` | Not closed, and the committed date has not passed |

`src/metrics.py` sums these buckets and reconciles them to the manifest row
count. If they do not match exactly, a request has escaped the classification
and the definitions are wrong.

### Why open and overdue requests count as misses

13,996 requests are unresolved and already past their committed date. They are
definitively late, whatever happens next.

Computing the on-time rate only on closed requests would drop all of them and
report a rate biased upward. Including them keeps the measure honest about work
the city has not delivered.

### Why open and not-yet-due requests are excluded

5,442 requests are unresolved but still inside their committed window. Their
outcome is genuinely unknown. Counting them as on time assumes success,
counting them as late assumes failure, and both invent information.

This is censoring. Excluding them and saying so is the correct treatment.

---

## 4. Metric definitions

| Metric | Definition | Population |
| --- | --- | --- |
| Requests received | Count of all requests | Intake |
| Duplicate rate | Duplicates as a percentage of intake | Intake |
| Service requests | Requests excluding duplicates | Service |
| Evaluable requests | On time plus late plus open-overdue | Evaluable |
| On-time requests | Closed on or before the committed date | Evaluable |
| **On-time rate** | On-time requests as a percentage of evaluable requests | Evaluable |
| Open overdue | Unresolved requests past their committed date | Service |
| Median days to close | Median calendar days from submission to closure | Closed only |
| Median days overdue | Median days an overdue open request has been past due | Open overdue |
| Deadline revision rate | Requests whose completion date was revised | Intake |

**Median, not mean, for elapsed days.** The distribution has a long right tail:
building inspections carry a 365-day commitment while trash collection carries
one day. A mean would describe no actual request.

**Calendar days, not business days.** The commitment itself is expressed in
calendar days, so the measure has to match it.

---

## 5. Where the on-time trend may be reported

Only for services whose committed completion time held steady across the whole
window. Check C20 established these four:

| Service | Commitment | Modal share, 2023 to 2026 | Requests |
| --- | --- | --- | --- |
| POTHOLE, REPAIR | 12 days | 98.3 to 99.2% | 25,997 |
| BUILDING, RESIDENTIAL | 365 days | 96.7 to 97.7% | 16,782 |
| TALL GRASS/WEEDS, PRIVATE PROP | 45 days | 89.1 to 97.4% | 14,848 |
| LITTER, PRIVATE PROPERTY | 45 days | 98.6 to 100% | 11,226 |

68,853 requests, 13.3 percent of the snapshot.

### Services excluded from trend reporting, and why

| Service | Change |
| --- | --- |
| TRASH, REQUEST FOR COLLECTION | 7 days in 2023, 1 day from 2024 |
| METAL FURNITURE, SPEC COLLECTN | Single 14-day commitment, then a 14/30 split from 2025 |
| TRASH, BULK ITEM PICK-UP | Type absent in 2023; 14/30 split from 2025 |
| 311 ASSISTANCE | Commitment stable, volume down about 72 percent in 2026 |

Where a commitment changed mid-window, an apparent improvement may reflect a
looser promise rather than faster service. Reporting such a trend as
performance would be an error.

Metal furniture and bulk item pickup are analysed as one family or not at all.
Volume migrated between them after 2024, so neither is comparable over time
alone.

Demand, backlog, and ageing measures are reported across all 517,287 requests,
because none of them depends on the commitment.

---

## 6. Dimensions

| Dimension | Field | Note |
| --- | --- | --- |
| Service type | `sr_type_desc` | Not stable over time; see section 5 |
| Department | `dept_name` | The decision owner |
| Division | `group_title` | |
| Neighborhood | `neighborhood` | See limitation below |
| Priority | `priority` | STANDARD, PRIORITY, HAZARDOUS |
| Intake channel | `method_received` | |
| Month | Derived from creation date | |

---

## 7. Stated limitations

1. **The publisher's definition of the commitment conflicts with the data.**
   The dictionary says the clock starts at response; the data starts it at
   submission, on 517,214 of 517,214 testable rows. The observed behaviour is
   used. See `reports/source_definitions.md`.

2. **Closure codes are undefined.** The publisher documents no value list for
   `SR_STATUS`. `CLOS-NO`, `ABAT-OWN`, `CLOS-RI`, `CLOS-EXP` and `CLOS-EOY` are
   treated as completed service. `src/metrics.py` runs a sensitivity test
   showing the on-time rate under alternative treatments, and the case study
   reports the range rather than a single unsupported number.

3. **Neighborhood is ambiguous.** `NEIGHBORHOOD` and
   `COMMUNITY_COUNCIL_NEIGHBORHOOD` disagree on 120,477 requests, 23.3 percent.
   The documented field is used. The undocumented one is never mixed in.

4. **Response timeliness cannot be measured.** `DATE_DISPATCHED` is blank on
   97.8 percent of rows, so there is no actual to compare against the response
   commitment. Only completion timeliness is reported.

5. **Whole days only.** Creation and closure dates carry no usable time
   component. Acceptable, because the commitment is also expressed in whole
   days.

6. **Two status signals disagree on 137 requests**, 0.026 percent. Closure is
   defined by the presence of a closure date rather than the status flag,
   because timeliness needs a date to compute.

7. **The trend covers 13.3 percent of volume.** The rest of the file cannot
   support a comparable trend because the commitment changed within the window.

8. **This is one city over one window.** Nothing here generalises to other
   municipalities, and no causal claim is made about why any measure moved.
