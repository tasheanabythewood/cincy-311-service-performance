"""
Step 8. Static charts for the website.

WHY STATIC AND NOT AN INTERACTIVE EMBED: an interactive BI embed is not
necessarily free, accessible, or safe to publish, and it adds a dependency
between your portfolio page and a vendor's uptime. A PNG renders everywhere,
loads instantly, prints, and cannot break. Interactivity is worth adding when a
reader needs to explore. A recruiter reading a case study needs to understand
one point per chart.

EVERY CHART GETS ALT TEXT, written here rather than left to the website build.
The alt text states what the chart shows and what it means, because a chart
whose point is invisible to a screen reader is a chart whose point is
invisible.

DESIGN TOKENS: defined once below and reused, so charts and the eventual site
share one visual language rather than drifting apart.

Usage:
    python -m src.charts
"""

from __future__ import annotations

import json
import textwrap

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from . import config, db

# ---------------------------------------------------------------------------
# Design tokens
#
# Palette: the Okabe-Ito colourblind-safe set. Chosen on purpose rather than as
# a house style. A project whose whole argument is that the data was checked
# properly should not then encode its findings in colours that roughly 1 in 12
# men cannot distinguish. It is also not the default matplotlib cycle, so the
# charts do not read as untouched output.
# ---------------------------------------------------------------------------
# Palette, set by the project owner. Seven values, of which only TWO carry
# hue: a pale sage and a dark forest green. Everything else is neutral.
#
# THAT CONSTRAINT IS THE DESIGN. A four-colour categorical chart is not
# available here, so the charts use two patterns instead, both of which are
# better practice anyway:
#
#   1. Ordinal data gets a SEQUENTIAL RAMP interpolated between sage and
#      forest. Age bands are ordered, so an ordered colour scale is correct;
#      four arbitrary hues were always the wrong encoding for them.
#   2. Categorical data gets HIGHLIGHT AND MUTE. The series the chart is about
#      is forest; everything else is mid grey. A reader is told where to look
#      rather than left to decode a legend.
#
# MEASURED CONTRAST ON WHITE (WCAG needs 4.5:1 for text, 3.0:1 for UI):
#   forest  #1a5442   8.78:1   safe for text, thin lines, small marks
#   midgrey #737373   4.74:1   safe for text
#   black   #000000  21.00:1   emphasis
#   sage    #bed4c8   1.56:1   DECORATIVE ONLY. Never text, never a thin line.
#   greys   #d9d9d9 / #eaeaea  1.4:1 and 1.2:1. Gridlines and fills only.
#
# Sage, light grey and off-white are within 1.3:1 of each other, so no two of
# them may ever sit adjacent as separate categories.
#
# THE ACCENT HAS ONE HARD RESTRICTION, measured rather than assumed:
#   alert  #8c2f1f   8.26:1 on white, 5.85:1 on light grey, 5.29:1 on sage
#   alert vs forest  1.06:1      relative luminance 0.077 against 0.070
#
# The accent and the forest green are the same brightness. They are separated
# by hue alone, they are identical in greyscale, and under simulated
# deuteranopia they sit at 1.22:1, which is to say indistinguishable. The same
# is true against mid grey (1.74:1) and black (2.54:1).
#
# So: the accent is for emphasis ON LIGHT BACKGROUNDS. It may never be a
# category placed beside forest, mid grey or black. Where two dark series are
# needed, use the ordinal ramp instead.
ALERT = "#8c2f1f"      # the thing to act on. See the restriction below.
INK = "#000000"        # emphasis, annotations, the point to look at
FOREST = "#1a5442"     # the primary data series
MIDGREY = "#737373"    # secondary series, axis text, source lines
MUTED = "#737373"      # alias: secondary text
SAGE = "#bed4c8"       # lightest step of the ordinal ramp; fills only
GRID = "#d9d9d9"       # gridlines
BAND = "#eaeaea"       # shaded season bands
PAPER = "#FFFFFF"

# Kept as names so existing chart code does not need rewriting.
BLUE = FOREST          # primary
VERMILLION = INK       # "the thing to act on" is now weight, not warmth
GREEN = MIDGREY
AMBER = "#9fb6aa"
SKY = "#759083"

# Sequential ramp, interpolated in LINEAR light rather than sRGB. sRGB
# interpolation darkens and desaturates the midpoints, which is why hand-mixed
# ramps often look muddy. Adjacent steps differ by at least 0.18 relative
# luminance, so the chart still reads when printed in greyscale.
RAMP_4 = ["#bed4c8", "#9fb6aa", "#759083", "#1a5442"]
RAMP_3 = ["#bed4c8", "#8ca498", "#1a5442"]

FONT = "Liberation Sans"   # metric-compatible with Helvetica, present on most systems

plt.rcParams.update({
    "figure.facecolor": PAPER,
    "axes.facecolor": PAPER,
    "font.family": FONT,
    "font.size": 11,
    "text.color": INK,
    "axes.labelcolor": INK,
    "axes.edgecolor": GRID,
    "axes.linewidth": 1.0,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.frameon": False,
    "figure.dpi": 110,
    "savefig.dpi": 220,        # retina-ready; the site serves it at half width
    "savefig.facecolor": PAPER,
})

PCT = FuncFormatter(lambda v, _: f"{v:.0f}%")
THOUSANDS = FuncFormatter(lambda v, _: f"{v:,.0f}")

CHARTS_DIR = config.PROJECT_ROOT / "reports" / "charts"


def _finish(fig, ax, title: str, subtitle: str, source: str) -> None:
    """
    Apply the shared frame: title, subtitle, source line, and a clean spine.

    The title states the FINDING, not the variable. "Bulky collection misses its
    commitment every summer" tells a reader what to take away; "On-time rate by
    month" makes them work it out. A chart in a case study is an argument and
    its title is the claim, which also means the title has to be true: if the
    data does not support the sentence, change the sentence, not the chart.

    Title, subtitle and source all align to the left edge of the plot area
    rather than the figure edge, so they line up with the y-axis label column
    whatever the figure size.
    """
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)

    # Reserve room above and below the axes for the text block.
    fig.subplots_adjust(top=0.80, bottom=0.17)
    x0 = ax.get_position().x0

    wrapped = textwrap.fill(subtitle, width=98)
    fig.text(x0, 0.965, title, ha="left", va="top",
             fontsize=15, fontweight="bold", color=INK)
    fig.text(x0, 0.895, wrapped, ha="left", va="top",
             fontsize=10.5, color=MUTED, linespacing=1.45)
    fig.text(x0, 0.03, textwrap.fill(source, width=120), ha="left", va="bottom",
             fontsize=8.5, color=MUTED, linespacing=1.4)


# ---------------------------------------------------------------------------
# Data access. Each returns a DataFrame; plotting is separate so the chart code
# can be tested without a database.
# ---------------------------------------------------------------------------

Q_MONTHLY_BULKY = """
SELECT
    d.year_month,
    d.year,
    d.month_number,
    SUM(f.request_count)                                     AS intake,
    SUM(f.mature_evaluable_count)                            AS evaluable,
    ROUND(100.0 * SUM(f.mature_on_time_count)
          / NULLIF(SUM(f.mature_evaluable_count), 0), 1)     AS on_time_pct,
    SUM(f.mature_evaluable_count) - SUM(f.mature_on_time_count) AS missed
FROM fact_service_request f
JOIN dim_date    d ON d.date_key    = f.created_date_key
JOIN dim_service s ON s.service_key = f.service_key
WHERE s.sr_type = 'MTL-FRN' AND d.year >= 2024
GROUP BY d.year_month, d.year, d.month_number
ORDER BY d.year_month
"""

Q_MAR_JUL = """
SELECT
    d.year,
    d.month_number,
    SUM(f.mature_evaluable_count)                            AS evaluable,
    ROUND(100.0 * SUM(f.mature_on_time_count)
          / NULLIF(SUM(f.mature_evaluable_count), 0), 1)     AS on_time_pct
FROM fact_service_request f
JOIN dim_date    d ON d.date_key    = f.created_date_key
JOIN dim_service s ON s.service_key = f.service_key
WHERE s.sr_type = 'MTL-FRN' AND d.month_number IN (3, 7) AND d.year >= 2024
GROUP BY d.year, d.month_number
ORDER BY d.year, d.month_number
"""

Q_BACKLOG_AGE = """
SELECT
    MODE(s.service_label)                                        AS service_label,
    SUM(CASE WHEN f.days_overdue_open <= 90 THEN 1 ELSE 0 END)   AS within_90d,
    SUM(CASE WHEN f.days_overdue_open BETWEEN 91 AND 365
             THEN 1 ELSE 0 END)                                  AS d91_365,
    SUM(CASE WHEN f.days_overdue_open BETWEEN 366 AND 730
             THEN 1 ELSE 0 END)                                  AS d1_2yr,
    SUM(CASE WHEN f.days_overdue_open > 730 THEN 1 ELSE 0 END)   AS over_2yr,
    SUM(f.open_overdue_count)                                    AS overdue
FROM fact_service_request f
JOIN dim_service s ON s.service_key = f.service_key
WHERE f.outcome = 'open, overdue'
GROUP BY s.sr_type
ORDER BY overdue DESC
LIMIT 8
"""

Q_SERVICE_TREND = """
SELECT
    s.sr_type,
    MODE(s.service_label)                                    AS service_label,
    MODE(s.modal_committed_days)                             AS days,
    d.year,
    SUM(f.mature_evaluable_count)                            AS evaluable,
    ROUND(100.0 * SUM(f.mature_on_time_count)
          / NULLIF(SUM(f.mature_evaluable_count), 0), 1)     AS on_time_pct
FROM fact_service_request f
JOIN dim_date    d ON d.date_key    = f.created_date_key
JOIN dim_service s ON s.service_key = f.service_key
WHERE s.stable_commitment
GROUP BY s.sr_type, d.year
HAVING SUM(f.mature_evaluable_count) > 0
ORDER BY s.sr_type, d.year
"""


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def chart_monthly(frame) -> tuple:
    fig, ax = plt.subplots(figsize=(10, 4.6))
    x = range(len(frame))
    y = frame["on_time_pct"].tolist()
    labels = frame["year_month"].tolist()

    # Shade June to September in every year: the window the recommendation targets.
    for i, m in enumerate(frame["month_number"]):
        if 6 <= int(m) <= 9:
            ax.axvspan(i - 0.5, i + 0.5, color=BAND, alpha=0.75, lw=0, zorder=0)

    ax.plot(x, y, color=BLUE, lw=2.2, marker="o", ms=4, zorder=3)
    ax.axhline(90, color=MUTED, lw=1, ls=(0, (4, 4)), zorder=2)
    ax.text(len(frame) - 0.5, 91, "90%", ha="right", va="bottom",
            fontsize=9, color=MUTED)

    # Label the worst point directly rather than relying on a reader to find it.
    low = int(min(range(len(y)), key=lambda i: y[i]))
    # The accent sits on white here, at 8.26:1, and the marker is separated
    # from the forest line by position as well as colour.
    ax.plot([low], [y[low]], marker="o", ms=9, color=ALERT, zorder=4)
    ax.annotate(f"{labels[low]}\n{y[low]:.1f}%",
                xy=(low, y[low]), xytext=(low + 1.2, y[low] + 16),
                fontsize=10, color=ALERT, fontweight="bold",
                arrowprops=dict(arrowstyle="-", color=ALERT, lw=1.2))

    ax.set_ylim(0, 104)
    ax.yaxis.set_major_formatter(PCT)
    ax.set_xticks([i for i, l in enumerate(labels) if l.endswith(("-01", "-04", "-07", "-10"))])
    ax.set_xticklabels([labels[i] for i in ax.get_xticks()], rotation=0)
    ax.set_ylabel("Met the 14-day commitment")

    _finish(fig, ax,
            "Bulky collection misses its commitment every summer",
            "Shaded bands are June to September. 2024 and 2026 recover each autumn. "
            "2025 was different: it declined from February and did not recover until "
            "October.",
            "Source: City of Cincinnati 311 service requests, snapshot 2026-09-18. "
            "Requests whose committed date had passed as of the snapshot.")

    alt = (
        "Line chart of the share of Cincinnati bulky-collection requests meeting the "
        "city's 14-day commitment, each month from January 2024 to August 2026. The "
        "rate sits between 95 and 99 percent through winter and spring in every year, "
        "then falls sharply each summer, reaching 36.6 percent in August 2024, 5.1 "
        "percent in August 2025 and 68.8 percent in August 2026. June to September is "
        "shaded in each year. 2025 declined from February onward and did not recover "
        "until October."
    )
    return fig, alt


def chart_missed_by_month(frame) -> tuple:
    fig, ax = plt.subplots(figsize=(10, 4.2))
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    years = sorted(frame["year"].unique())
    colors = {2024: RAMP_3[0], 2025: RAMP_3[1], 2026: RAMP_3[2]}
    width = 0.8 / len(years)

    for k, yr in enumerate(years):
        sub = frame[frame["year"] == yr].set_index("month_number")["missed"]
        vals = [float(sub.get(m, 0)) for m in range(1, 13)]
        offs = [i - 0.4 + width * (k + 0.5) for i in range(12)]
        ax.bar(offs, vals, width=width * 0.92,
               color=colors.get(int(yr), MUTED), label=str(int(yr)))

    ax.set_xticks(range(12))
    ax.set_xticklabels(months)
    ax.yaxis.set_major_formatter(THOUSANDS)
    ax.set_ylabel("Requests that missed the commitment")
    ax.legend(loc="upper left", ncols=len(years), fontsize=10)

    _finish(fig, ax,
            "Four months carry most of the year's missed commitments",
            "In 2024, 84 percent of the year's misses fell between June and September. "
            "2026 data ends in August.",
            "Source: City of Cincinnati 311 service requests, snapshot 2026-09-18.")

    alt = (
        "Grouped bar chart of bulky-collection requests that missed their commitment, "
        "by calendar month, for 2024, 2025 and 2026. Misses are near zero from October "
        "to May in 2024 and 2026 and rise steeply in June, July and August. 2025 is "
        "elevated from February onward and peaks above 2,900 in July. In 2024, 84 "
        "percent of the year's misses fell between June and September."
    )
    return fig, alt


def chart_volume_vs_ontime(frame) -> tuple:
    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    years = sorted(frame["year"].unique())
    x = range(len(years))
    mar = [float(frame[(frame.year == y) & (frame.month_number == 3)]["on_time_pct"].iloc[0])
           for y in years]
    jul = [float(frame[(frame.year == y) & (frame.month_number == 7)]["on_time_pct"].iloc[0])
           for y in years]
    mar_v = [float(frame[(frame.year == y) & (frame.month_number == 3)]["evaluable"].iloc[0])
             for y in years]
    jul_v = [float(frame[(frame.year == y) & (frame.month_number == 7)]["evaluable"].iloc[0])
             for y in years]

    # March is the reference month and July is the problem, so July takes the
    # accent. Sage against the accent is 5.29:1, and still 4.71:1 under
    # simulated deuteranopia. Sage gets a forest edge because at 1.56:1 on
    # white a sage fill has no boundary of its own.
    ax.bar([i - 0.19 for i in x], mar, width=0.36, color=SAGE,
           edgecolor=FOREST, linewidth=1.0, label="March")
    ax.bar([i + 0.19 for i in x], jul, width=0.36, color=ALERT, label="July")

    for i, y in enumerate(years):
        change = (jul_v[i] / mar_v[i] - 1) * 100
        ax.text(i, max(mar[i], jul[i]) + 4,
                f"July carried {change:+.0f}% volume\nand lost {mar[i]-jul[i]:.0f} points",
                ha="center", fontsize=9, color=MUTED)

    ax.set_xticks(list(x))
    ax.set_xticklabels([str(int(y)) for y in years])
    ax.set_ylim(0, 128)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.yaxis.set_major_formatter(PCT)
    ax.set_ylabel("Met the 14-day commitment")
    # Legend above the plot area, not inside it: at these bar heights any
    # in-axes position overlaps a bar in at least one year.
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.20), ncols=2, fontsize=10)

    _finish(fig, ax,
            "Demand alone does not explain the summer failure",
            "July carries only slightly more volume than March, and performs far worse "
            "in every year.",
            "Source: City of Cincinnati 311 service requests, snapshot 2026-09-18.")

    alt = (
        "Paired bar chart comparing the bulky-collection on-time rate in March and July "
        "for 2024, 2025 and 2026. March is high in 2024 and 2026 at 97.9 and 97.3 "
        "percent, while July falls to 62.8 and 76.2 percent. In 2025 March is already "
        "depressed at 63.1 percent and July falls to 8.5 percent. Annotations show July "
        "carried 22, 2 and 10 percent more volume than March respectively, far too "
        "little to account for losses of 35, 55 and 21 percentage points."
    )
    return fig, alt


def chart_backlog_age(frame) -> tuple:
    frame = frame.iloc[::-1]
    fig, ax = plt.subplots(figsize=(9.6, 4.8))
    labels = [s.title() for s in frame["service_label"]]
    # Ordered bands get an ordered scale: pale for recent, dark for oldest.
    bands = [("within_90d", "Under 90 days", RAMP_4[0]),
             ("d91_365", "91 days to 1 year", RAMP_4[1]),
             ("d1_2yr", "1 to 2 years", RAMP_4[2]),
             ("over_2yr", "Over 2 years", RAMP_4[3])]

    left = [0.0] * len(frame)
    for col, label, color in bands:
        vals = frame[col].astype(float).tolist()
        ax.barh(labels, vals, left=left, color=color, label=label, height=0.62)
        left = [a + b for a, b in zip(left, vals)]

    ax.xaxis.set_major_formatter(THOUSANDS)
    ax.set_xlabel("Open requests past their committed date")
    ax.legend(loc="lower right", ncols=2, fontsize=9.5)
    ax.grid(axis="y", visible=False)

    _finish(fig, ax,
            "The building backlog is old; the collection backlog is not",
            "Residential inspection holds 3,389 overdue requests, 57 percent of them "
            "more than a year past due. Bulky collection clears within 90 days.",
            "Source: City of Cincinnati 311 service requests, snapshot 2026-09-18.")

    alt = (
        "Horizontal stacked bar chart of open, overdue requests for the eight services "
        "with the largest backlogs, split by how long they have been past their "
        "committed date. Residential building inspection has the largest backlog at "
        "3,389 requests, of which 1,929 are more than a year overdue and 638 more than "
        "two years. Bulky collection has 1,527 overdue but almost all are under 90 "
        "days. Several smaller building and permit services consist almost entirely of "
        "requests more than a year overdue."
    )
    return fig, alt


def chart_service_trend(frame) -> tuple:
    fig, ax = plt.subplots(figsize=(8.8, 4.6))
    # Highlight and mute. Residential inspection is the finding; the other
    # three are context. Two hues cannot carry four categories, and forcing it
    # would produce a legend nobody decodes.
    colors = {"BLD-RES": FOREST, "PTHOLE": MIDGREY,
              "LITR-PRV": "#9fb6aa", "TLGR-PRV": "#759083"}
    # Direct labels beat a legend, but only if they do not collide. Litter and
    # tall grass finish within 2 points of each other, so the label positions
    # are nudged apart until no two are closer than a readable gap.
    endpoints = []
    for code, sub in frame.groupby("sr_type"):
        sub = sub.sort_values("year")
        ax.plot(sub["year"], sub["on_time_pct"], marker="o", ms=5, lw=2.2,
                color=colors.get(code, MUTED))
        last = sub.iloc[-1]
        endpoints.append((float(last["on_time_pct"]), float(last["year"]), code,
                          f"{last['service_label'].title()} ({int(last['days'])}d)"))

    MIN_GAP = 6.0
    endpoints.sort()
    placed: list[float] = []
    for value, year, code, label in endpoints:
        y = value
        while placed and abs(y - placed[-1]) < MIN_GAP:
            y = placed[-1] + MIN_GAP
        placed.append(y)
        ax.annotate(label, xy=(year, value), xytext=(year + 0.08, y),
                    va="center", fontsize=9.5, color=colors.get(code, MUTED))

    ax.set_xticks(sorted(frame["year"].unique()))
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(PCT)
    ax.set_ylabel("Met the committed date")
    ax.set_xlim(right=max(frame["year"]) + 1.6)

    _finish(fig, ax,
            "Three services improved; residential inspection did not",
            "Only these four held the same committed time across the window, so only "
            "these support a trend. Residential inspection has no mature 2026 cohort: "
            "nothing created in 2026 is due yet.",
            "Source: City of Cincinnati 311 service requests, snapshot 2026-09-18. "
            "Each year covers requests whose committed date had passed.")

    alt = (
        "Line chart of the on-time rate from 2023 to 2026 for the four Cincinnati 311 "
        "services whose committed completion time did not change during the period. "
        "Pothole repair, on a 12-day commitment, stays between 91 and 96.6 percent. "
        "Litter on private property and tall grass and weeds, both on 45 days, rise "
        "from the low 80s and mid 70s to the low 90s. Residential building inspection, "
        "on 365 days, rises from 44.8 percent in 2023 to 64.1 in 2024 then falls to "
        "59.0 in 2025, and has no 2026 point because no request created in 2026 has "
        "reached its committed date."
    )
    return fig, alt


CHARTS = [
    ("01-bulky-monthly-on-time", Q_MONTHLY_BULKY, chart_monthly),
    ("02-missed-by-month", Q_MONTHLY_BULKY, chart_missed_by_month),
    ("03-volume-vs-on-time", Q_MAR_JUL, chart_volume_vs_ontime),
    ("04-backlog-age", Q_BACKLOG_AGE, chart_backlog_age),
    ("05-stable-service-trend", Q_SERVICE_TREND, chart_service_trend),
]


def run() -> None:
    source, snapshot_date = db.latest_snapshot()
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    con = db.connect_warehouse(source)

    alts: dict[str, str] = {}
    for name, sql, plotter in CHARTS:
        frame = con.execute(sql).fetchdf()
        fig, alt = plotter(frame)
        png = CHARTS_DIR / f"{name}.png"
        svg = CHARTS_DIR / f"{name}.svg"
        # bbox_inches="tight" so long category labels and end-of-line labels
        # are never clipped at the figure edge.
        fig.savefig(png, bbox_inches="tight")
        fig.savefig(svg, bbox_inches="tight")
        plt.close(fig)
        alts[name] = alt
        print(f"  {name:<28}{frame.shape[0]:>4} rows  ->  {png.name}, {svg.name}")

    (CHARTS_DIR / "alt_text.json").write_text(json.dumps(alts, indent=2))
    lines = ["# Chart alt text", "",
             "Copy these into the `alt` attribute when the charts go on the site.",
             "A chart whose point is invisible to a screen reader is a chart whose "
             "point is invisible.", ""]
    for name, alt in alts.items():
        lines += [f"## {name}", "", alt, ""]
    (CHARTS_DIR / "alt_text.md").write_text("\n".join(lines))

    con.close()
    print(f"\n  {len(CHARTS)} charts written to {CHARTS_DIR}")
    print(f"  alt text in alt_text.md and alt_text.json")


if __name__ == "__main__":
    run()
