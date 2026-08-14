---
name: hotel-investment-underwriting
description: Collect page-sourced 2km pure-esports competitor evidence and run deterministic Chinese co-operated esports-hotel underwriting. Use for address screening, competitor room/photo/price evidence, ADR review, CapEx/return/monthly payback, HTML, or Feishu Bitable delivery.
---

# Hotel Investment Underwriting

Use this stateless Skill once per opportunity. Code decides distance, classification, ADR and finance.

## Flow

1. Run `collect_market_evidence.py` with an explicit Profile (Playwright, Ego Lite, Ui.Vision+OpenCLI, Kimi, crawl4ai or xcrawl). It returns a portable receipt; never use Codex UI as evidence.
2. Merge its `skill-patch` and `project_input`, then call `run.py`. Competitor/report fields must exactly match `market_evidence`.
3. Read two states: `collection_result.status` covers all evidence; `spatial_collection` proves the full 2km map pool. Partial OTA evidence may preserve the spatial result but never creates ADR.

## Non-negotiable rules

- Keep only same-provider GCJ-02, sourced, operating primary-esports lodging within 2km. Do not infer facts or widen range.
- Pass the full map pool to OTA as `candidate_pool`; its centre, Profile, count and sorted provider-ID hash must return unchanged. Deep OTA/visual research is deterministically capped at **8** properties.
- ADR needs one `pricing_context`, complete spatial collection and three independent same-workstation medium/high-confidence properties; use CNY-10-rounded median. Never write it into finance automatically.
- Ego `ctrip-hotel-v1` supplies report-only P1 DOM evidence. Ui.Vision `ctrip-live-rates-v1` can create ADR offers only after the bounded offline Scrapling DOM parser, exact context, Network/DOM agreement, availability, tax, cancellation and workstation checks. Exact-name Ctrip mapping also requires address-city agreement; an unverified page context or parser schema drift is never ADR-eligible.
- Finance is code-only. JPEG/PNG/WebP visual evidence must bind to a formal `provider_place_id` and is presentation-only. Credentials, Base writeback and state remain with the host. On a new Mac Mini, run `collect_market_evidence.py --preflight --all-engines` and act on its install hints.

```bash
python3 scripts/collect_market_evidence.py --input /path/to/collection-request.json --format skill-patch
python3 scripts/run.py --input /path/to/skill-request.json --defaults references/benchmark-defaults.json --format feishu
```

Use `--format json`, `html` or `bitable`. Read `market-evidence-collection.md` for the collection contract, `market-evidence-runtime.md` for deployment, `input-schema.md` for finance, and `bitable-delivery.md` for Base.
