# Palette and chart colour rules

Seven values, set by the project owner. Applied in `src/charts.py` and reused
by the website so the two cannot drift apart.

| Token | Hex | Contrast on white | Use |
| --- | --- | --- | --- |
| Forest | `#1a5442` | 8.78:1 | Primary data series, links, headings |
| Alert | `#8c2f1f` | 8.26:1 | Emphasis on light backgrounds. See restriction below |
| Mid grey | `#737373` | 4.74:1 | Secondary series, axis text, source lines |
| Black | `#000000` | 21.00:1 | Emphasis, annotations, body text |
| Sage | `#bed4c8` | 1.56:1 | Fills only. Never text, never a thin line |
| Light grey | `#d9d9d9` | 1.41:1 | Gridlines, rules, borders |
| Off white | `#eaeaea` | 1.20:1 | Shaded bands, section backgrounds |
| White | `#ffffff` | reference | Page and chart background |

Contrast ratios measured, not estimated. WCAG requires 4.5:1 for normal text
and 3.0:1 for large text and interface elements.

## The constraint, and why it improved the charts

Only two of the seven values carry hue. A four-colour categorical chart is not
available, so the charts use two patterns instead. Both are better practice
than a four-hue palette would have been.

**Ordered data gets a sequential ramp.** Backlog age bands and years are
ordered, so they get an ordered colour scale interpolated between sage and
forest. Four arbitrary hues were always the wrong encoding for an ordered
variable.

```
4 steps   #bed4c8   #9fb6aa   #759083   #1a5442
3 steps   #bed4c8   #8ca498   #1a5442
```

Interpolated in linear light rather than sRGB, because sRGB interpolation
darkens and desaturates the midpoints and produces a muddy ramp. Adjacent steps
differ by at least 0.18 relative luminance, so the chart still reads when
printed in greyscale or viewed by someone with any form of colour vision
deficiency.

**Categorical data gets highlight and mute.** The series the chart is about is
forest; the rest are grey. The reader is told where to look instead of being
handed a legend to decode.

## The alert colour has one restriction

Measured, not assumed:

| Pair | Normal vision | Deuteranopia |
| --- | --- | --- |
| Alert vs white | 8.26:1 | fine |
| Alert vs light grey | 5.85:1 | fine |
| Alert vs sage | 5.29:1 | 4.71:1 |
| **Alert vs forest** | **1.06:1** | **1.22:1** |
| Alert vs mid grey | 1.74:1 | 1.57:1 |
| Alert vs black | 2.54:1 | 2.82:1 |

Alert and forest have relative luminances of 0.077 and 0.070. They are the same
brightness, separated by hue alone. They are identical in greyscale, identical
to a printer, and indistinguishable under the common forms of colour vision
deficiency.

**The alert colour may never be a category placed beside forest, mid grey or
black.** It is for emphasis on light backgrounds: annotations, a marked data
point, a callout, a warning band, one bar against a sage one. Where two dark
series are genuinely needed, use the ordinal ramp instead.

Applied in the charts as:
- the marked worst point and its label on the monthly series
- the July bars against sage March bars in the March-versus-July comparison

## Hard rules

1. **Sage never carries text or a thin line.** At 1.56:1 on white it is
   invisible to many readers. Fills and large blocks only.
2. **Sage, light grey and off white never sit adjacent as separate
   categories.** They are within 1.3:1 of each other and cannot be told apart.
3. **The alert colour never touches forest, mid grey or black.** Same
   brightness, hue-only separation, invisible in greyscale. Pair it with white,
   off white, light grey or sage.
4. **Colour never carries meaning alone.** Every series is also identifiable by
   position, direct label, or its place in an ordered scale.
