---
name: hotel-investment-underwriting
description: Run mandatory 2km pure-esports competitor analysis and deterministic Chinese co-operated esports-hotel underwriting. Use for address screening, ADR evidence, CapEx/return/monthly payback, visual HTML, or Feishu Bitable delivery.
---

# Hotel Investment Underwriting

One stateless Skill per hotel opportunity. Bundled code, not model prose, decides distance, classification, ADR and finance.

## Request

Call only `scripts/run.py` with `project_input`, `competitor_analysis`, and optional `competitor_report`. Financial input follows `schemas/project-input.schema.json`; the unified envelope, evidence, offers and media follow `schemas/skill-request.schema.json`.

Missing or incomplete `competitor_analysis` returns only `pre_evaluation_only`. `competitor_report` and optional candidate `market_profile` are delivery-only; neither changes classification, ADR or finance.

## Fixed sequence

1. Obtain a user-confirmed GCJ-02 center from an authorized map source; resolve ambiguity with the user.
2. Collect same-provider candidates; use `complete` only after the defined search finishes, otherwise `partial`.
3. Run the entrypoint; it applies the unrounded 0–2,000 m Haversine boundary and exposes gaps.
4. Recommend ADR only with complete collection, valid shared `pricing_context`, at least three independent formal same-workstation properties, and `medium`/`high` confidence. Use the cross-property median, rounded to CNY 10.
5. Explicitly select the financial revenue assumption; return conclusion, risks, confidence and missing evidence.
6. For Base delivery, emit the manifest after this result; the authorized host writes it.

## Non-negotiable rules

- Formal competitors are operating `pure_esports_hotel` properties within 2km with the center's provider, place ID, GCJ-02 coordinates and source. Exclude incidental, non-lodging, closed, out-of-range and incomplete evidence; show low-confidence properties but never sample their ADR.
- Never widen radius or infer coordinates, status, positioning, source, ADR, OCC or room facts. Incomplete evidence is `evidence_insufficient` and caps finance at `pre_evaluation_only`.
- Finance is code-only: never calculate NPV, IRR, payback, break-even OCC or negotiation floors in prose, nor write competitor ADR into financial input automatically.
- Visual evidence must bind to a formal `provider_place_id`; HTML accepts only JPEG/PNG/WebP `data:image/...;base64,...` bytes with caption and source URL, never remote images.
- Credentials, external tools, storage, approval, dispatch and Base writeback stay in the host; this Skill owns no crawler, database or workflow state.

## Run and read selectively

```bash
python3 scripts/run.py --input /path/to/skill-request.json \
  --defaults references/benchmark-defaults.json --format feishu
```

Use `--format json` for structured output, `--format html > /path/to/competitor-research.html` for the responsive report, or `--format bitable > /path/to/bitable-delivery.json` for a standard Base manifest. Read `references/input-schema.md` for finance fields, `references/bitable-delivery.md` only for Base delivery, and `references/methodology.md` plus `references/decision-policy.md` only to explain results.
