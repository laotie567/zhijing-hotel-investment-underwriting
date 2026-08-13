# Underwriting methodology

Use one deterministic sequence:

`input validation → 2km competitor evidence → revenue → public costs → revenue sharing → party cash flow → return metrics → decision conditions`

Keep facts, benchmarks, assumptions and calculated outputs separate. A
benchmark or a model output never becomes a verified project fact merely
because it is present in the request.

## 2km competitor evidence

The Skill calculates unrounded Haversine distance from the confirmed GCJ-02
center. The formal set contains only operating, primary esports lodging within
0–2,000 meters with a complete source record. Ordinary hotels with incidental
esports rooms, non-lodging places, closed properties and out-of-range places
are not formal competitors.

Every candidate must come from the same map `provider` as the confirmed center,
so one provider's entity ID is never used to represent another's. For each
workstation count, normalize multiple room offers from the same property to
that property's median. Produce a suggested ADR only with a complete candidate
collection, one valid shared pricing context (check-in date, nights, guests and
CNY), and at least three independent formal properties whose sources are
`medium` or `high` confidence. Keep low-confidence-source properties visible,
but exclude their offers from the ADR sample. Round the cross-property median
to CNY 10. Until every gate passes, expose the candidate offers and sample
counts but no aggregate minimum, median, maximum or suggested ADR. The
suggested ADR is evidence for a human reviewer; it never writes
`revenue.egame_adr` automatically.

## Revenue and costs

For `adr_occ` mode:

`overnight revenue = esports ADR × rooms × OCC × operating days`

For `revpar` mode:

`overnight revenue = esports RevPAR × rooms × operating days`

With room types, calculate each room type independently, then derive blended
OCC and ADR from occupied room nights. Do not use simple averages. Calculate
hourly revenue and ancillary revenue separately and do not assume that they are
incremental when they consume the same inventory as overnight rooms.

Deduct common public costs before sharing revenue:

`distributable net revenue = gross revenue − public costs − turnover tax`

Then calculate each party's cash flow from its share revenue minus its own
costs. Keep the owner incremental and fully loaded views separate. When a
credible traditional-room baseline exists, report owner economic increment
after the replaced traditional-room contribution once, and only once.

## Returns and decision conditions

- NPV discounts the complete cash-flow series including year zero.
- IRR is meaningful only when cash flows change sign; otherwise use NPV and
  sustained payback as the primary signals.
- Sustained payback is the earliest point after which cumulative cash flow does
  not turn negative again.
- `static_payback_months` follows the original company investment workbook's
  `回款周期/月` convention: initial one-time CapEx divided by first-year average
  monthly operating net cash. It deliberately excludes later equipment
  replacement and terminal value, and returns both the raw month value and a
  conservative whole-month value rounded up.
- `discounted_payback_months` is the existing discounted sustained-payback
  result expressed as months (`1 year = 12 months`) and likewise returns a
  conservative whole-month value. It retains the annual cash-flow model's
  replacement, terminal-value and discounting convention; it does not invent a
  monthly forecast where the input has none.
- The exit redline uses every available rolling six-month OCC window; without
  enough monthly data it is `not_checked`, never assumed to pass.
- Negotiation boundaries solve the minimum JWL share and maximum initial CapEx
  at the stated hurdle IRR.

The final recommendation is capped by hard feasibility failures, source-backed
confidence, forecast validation and material financial risks. If 2km evidence
is incomplete, the combined Skill result and its nested financial result expose
`conclusion_scope=pre_evaluation_only`; do not present it as a completed
competitor conclusion.

## HTML competitor-research delivery

`--format html` is a presentation pass after the same deterministic workflow,
not a second research or decision engine. It lists the 2km analysis boundary,
formal competitors, room-type offers, available ADR references, exclusions,
the computed investment-return/month-level-payback table and the overall
conclusion scope. Its dedicated visual benchmark section combines
optional renovation observations and selected room images with the matching
formal competitor's room offers and distance for human product/price review.
These are sourced evidence attached to the corresponding formal competitor ID.
The renderer embeds its styles and supplied image bytes, so the saved HTML can
be opened offline; source links remain traceability links only. It cannot
upgrade `pre_evaluation_only` evidence to a completed conclusion or automatically
change ADR or financial assumptions.
