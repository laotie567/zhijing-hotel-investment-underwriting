---
name: hotel-investment-underwriting
description: Collect page-sourced 2km pure-esports competitor evidence and run deterministic Chinese co-operated esports-hotel underwriting. Use for address screening, competitor room/photos/availability-price evidence, ADR review, CapEx/return/monthly payback, visual HTML, or Feishu Bitable delivery.
---

# Hotel Investment Underwriting

One stateless Skill per opportunity. Code decides 2km distance, classification, ADR and finance.

## Required flow

1. Call `collect_market_evidence.py` with `market-evidence-collection/v1`. It uses an explicit Playwright/Ego Lite/Ui.Vision+OpenCLI/Kimi WebBridge/crawl4ai/xcrawl Profile, returns a receipt and never needs Codex UI.
2. Merge its `skill-patch` (including `market_evidence`) with `project_input`; call `run.py`. Any receipt mismatch is rejected.
3. Keep `partial` until every required evidence dimension completes. Collect the full 2km population first; price/image checks apply only to the explicit benchmark set. Then review code-derived 2km results, explicitly select finance inputs and, if needed, generate Base manifest/HTML.

## Rules

- Formal competitors: same-provider, GCJ-02, operating primary-esports lodging within 2km with source. Never infer facts or widen range; incomplete evidence is `pre_evaluation_only`.
- ADR requires complete collection, one `pricing_context`, three independent same-workstation `medium`/`high` properties; use median rounded to CNY 10. Never auto-write it into finance.
- `ctrip-hotel-v1` runs through the authenticated Ego Lite task space. It records P1 (DOM) room type, availability, final displayed price, cancellation text and hotel/room-gallery images. P1 is a report/Base evidence record only: it never enters ADR because the Profile does not inspect Network payloads or infer tax scope/machine count.
- `ctrip-live-rates-v1` uses Ui.Vision as the sole Ctrip page-action owner and OpenCLI only for Network/DOM observation. A P1/P2/P3 page price may be delivered as a `pricing_observation`; it enters `room_offers` and ADR only after exact context, Network/DOM agreement, availability, tax, cancellation and machine-count checks all pass.
- Finance is code-only. Visual evidence binds to a formal `provider_place_id` and is bounded JPEG/PNG/WebP `data_uri` plus source URL; it never changes finance.
- Credentials, sessions, storage, approval, dispatch and Base writeback stay in the host. On a new Mac Mini run `collect_market_evidence.py --preflight --all-engines`; obey its install hints. The collector has no UI, database or workflow state and never silently swaps engine/Profile.

## Commands

```bash
python3 scripts/collect_market_evidence.py --input /path/to/collection-request.json \
  --format skill-patch > /path/to/market-evidence-patch.json
python3 scripts/run.py --input /path/to/skill-request.json \
  --defaults references/benchmark-defaults.json --format feishu
```

Use `--format json`, `html`, or `bitable` on `run.py`. Read `references/market-evidence-collection.md` for contracts, `market-evidence-runtime.md` for Mac Mini/Hermes engines, `input-schema.md` for finance, `bitable-delivery.md` for Base, and `methodology.md`/`decision-policy.md` only to explain results.
