---
name: hotel-investment-underwriting
description: Evaluate a Chinese co-operated esports hotel before signing by running mandatory 2km pure-esports competitor analysis and deterministic investment underwriting in one Skill. Use for property/address screening, competitor-based ADR reference, room-type pricing and visual-photo benchmarking, CapEx/return and month-level payback calculation, negotiation floors, Feishu-ready pre-investment conclusions, and standalone HTML competitor-research delivery for 智竞未来 or similar esports-hotel conversions.
---

# Hotel Investment Underwriting

Run one stateless Skill for one hotel opportunity. Use the model only for intake and explanation; bundled code decides distance, classification, ADR, and finance.

## Request

Call only `scripts/run.py` with `project_input`, `competitor_analysis`, and optional `competitor_report`. `project_input` must pass `schemas/project-input.schema.json`; the unified envelope, evidence, offers, and media contract are in `schemas/skill-request.schema.json`.

`competitor_analysis` is a required business stage: absent or incomplete evidence yields only `pre_evaluation_only`, never a hidden 2km conclusion. `competitor_report` is presentation-only and cannot change classification, ADR, or finance.

## Fixed sequence

1. Obtain one user-confirmed GCJ-02 center from an authorized map source; ask the user to choose if it is ambiguous.
2. Collect candidates from the same provider. Use `complete` only after its defined search finishes; otherwise use `partial`.
3. Run the entrypoint. It applies the unrounded 0–2000 m Haversine boundary and exposes evidence gaps.
4. Recommend ADR only with a complete collection, at least three independent formal competitors, same-workstation offers, one valid `pricing_context`, and `medium`/`high` confidence. Use the cross-property median, rounded to CNY 10.
5. Explicitly choose the financial revenue assumption after reviewing competitors. Return both conclusions, risks, confidence, and missing evidence.

## Non-negotiable rules

- Formal competitors are operating `pure_esports_hotel` properties within 2km, with the center's provider, place ID, GCJ-02 coordinates, and source record. Exclude incidental rooms, non-lodging, closed/out-of-range properties, and incomplete pricing evidence. Show low-confidence properties, but never sample their prices for ADR.
- Never widen the radius or infer coordinates, status, positioning, source facts, ADR, OCC, or room facts. Incomplete evidence returns `evidence_insufficient` and caps finance as `pre_evaluation_only`.
- Finance is code-only: never calculate its NPV, IRR, payback, break-even OCC, or negotiation floors in prose, or automatically write competitor ADR into financial input.
- Visual evidence must bind to a formal `provider_place_id`. Portable HTML embeds JPEG/PNG/WebP `data:image/...;base64,...` bytes with caption and source URL; it never uses remote image files or invents missing visuals.
- Map/crawler credentials, storage, approvals, and dispatch stay in the host. This Skill owns no database, crawler service, workflow state, or writeback.

## Run and read selectively

```bash
python3 scripts/run.py --input /path/to/skill-request.json \
  --defaults references/benchmark-defaults.json --format feishu
```

Use `--format json` for structured output or `--format html > /path/to/competitor-research.html` for the standalone, responsive, no-JavaScript report. Read `references/input-schema.md` for finance fields and `references/methodology.md` plus `references/decision-policy.md` only when explaining results.
