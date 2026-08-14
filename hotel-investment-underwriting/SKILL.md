---
name: hotel-investment-underwriting
description: Collect page-sourced 2km pure-esports competitor evidence and run deterministic Chinese co-operated esports-hotel underwriting. Use for address screening, competitor room/photo/price evidence, ADR review, CapEx/return/monthly payback, HTML, or Feishu Bitable delivery.
---

# Hotel Investment Underwriting

Use this stateless Skill once per opportunity. Code decides distance, classification, ADR and finance.

## Flow

1. Mac Mini 的默认路径是：先用 Playwright/`360-map-v1` 建立完整 2km 候选池，再用 Ego Lite/`ctrip-hotel-v1` 深度采集最多 8 家标杆。只有需要 P2 Network/DOM 强校验时才显式启用 Ui.Vision+OpenCLI；采集器返回可移植回执，绝不把 Codex UI 当证据。
2. Merge its `skill-patch` and `project_input`, then call `run.py`. Competitor/report fields must exactly match `market_evidence`.
3. Read two states: `collection_result.status` covers all evidence; `spatial_collection` proves the full 2km map pool. Partial OTA evidence may preserve the spatial result but never creates ADR.

## Non-negotiable rules

- Keep only same-provider GCJ-02, sourced, operating primary-esports lodging within 2km. Do not infer facts or widen range.
- Pass the full map pool to OTA as `candidate_pool`; its centre, Profile, count and sorted provider-ID hash must return unchanged. Deep OTA/visual research is deterministically capped at **8** properties.
- ADR needs one `pricing_context`, complete spatial collection and three independent same-workstation medium/high-confidence properties; use CNY-10-rounded median. Never write it into finance automatically.
- Ego `ctrip-hotel-v1` 是 Mac Mini 的 OTA 主 Profile：交付房型、公开图片和同条件 P1 页面价格/无房结论，P1 只用于报告与飞书，不进入 ADR。可选的 Ui.Vision `ctrip-live-rates-v1` 只有在需要 P2 时才启用；它必须通过离线 Scrapling、完全相同的口径、Network/DOM 一致、可订、税费、取消和机位数检查。未经验证的页面或解析漂移永远不能 ADR-eligible。
- `ctrip-live-rates-v1` requires **exactly one** connected OpenCLI Browser Bridge Profile: the dedicated `ctrip-price-worker` Profile marked `default`. If another Chrome Profile is connected, preflight must stop the run before any Ctrip page action.
- Finance is code-only. JPEG/PNG/WebP visual evidence must bind to a formal `provider_place_id` and is presentation-only. Credentials, Base writeback and state remain with the host. On a new Mac Mini, run `collect_market_evidence.py --preflight --engine ego-browser` and act on its install hints; optional Profiles are checked only when enabled.

```bash
python3 scripts/collect_market_evidence.py --input /path/to/collection-request.json --format skill-patch
python3 scripts/run.py --input /path/to/skill-request.json --defaults references/benchmark-defaults.json --format feishu
```

Use `--format json`, `html` or `bitable`. Read `market-evidence-collection.md` for the collection contract, `market-evidence-runtime.md` for deployment, `input-schema.md` for finance, and `bitable-delivery.md` for Base.
