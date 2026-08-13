# Financial input contract

Pass financial data only as `project_input` inside the unified request to
`scripts/run.py`. `calculate.py` is an internal module and is not a supported
command-line entrypoint.

The public entrypoint validates `project_input` against
`schemas/project-input.schema.json` before it calculates. Unknown fields,
wrong types, invalid ranges and missing required fields are rejected. Amounts
use CNY; rates use decimals (`0.7` means 70%).

## Required blocks

| Block | Required core facts |
|---|---|
| `project` | `name`, `rooms`, `term_years`, `operating_days`; provide `workstations` or `seats_per_room`. |
| `contract` | JWL/owner shares, exit OCC redline, depreciation years, high/low-season assumptions. |
| `revenue` | `mode`, base OCC, overnight-revenue driver, hourly and ancillary assumptions. |
| `public_costs` | OTA, traffic, promotion, OTA-performance and turnover-tax inputs. |
| `jwl` | CapEx, monthly OpEx and replacement rule. |
| `owner` | CapEx, incremental monthly costs and fully loaded monthly costs. |
| `finance` | discount rate, hurdle IRR, maximum payback and exit-OCC safety buffer. |

Use `adr_occ` with `egame_adr` and `base_occ`, or `revpar` with
`egame_revpar`. Do not add both modes' revenue drivers as if they were
independent income.

## Optional but useful facts

- `revenue.room_types`: room-level mix. Each row needs a name, room count,
  workstations per room and the mode's revenue driver. Room and workstation
  totals must tie to `project`.
- `revenue.first_year_monthly_occ_schedule`: exactly 12 values with
  `project.opening_date`; use it for the opening ramp and six-month exit check.
- `revenue.annual_occ_schedule`: annual ramp when a monthly schedule is not
  available.
- `revenue.traditional_*`: use only when a credible traditional-room baseline
  exists; it enables the owner economic-increment view.
- `metadata`: declare data confidence and cite source records. Missing evidence
  lowers confidence; it is never silently promoted to a fact.
- `scenarios`: named OCC or override cases for downside/upside review.

## Unified request example

```json
{
  "project_input": {
    "project": {"name": "示例酒店", "rooms": 20, "workstations": 40, "term_years": 3, "operating_days": 365},
    "contract": {"jwl_share": 0.5, "owner_share": 0.5, "exit_occ_threshold": 0.6, "equipment_depreciation_years": 3, "renovation_depreciation_years": 3, "high_season_share": 0.4, "high_season_premium": 0.3, "low_season_premium": 0.1},
    "revenue": {"mode": "adr_occ", "base_occ": 0.65, "egame_adr": 260, "hourly_eligible_room_share": 0, "hourly_turnovers_per_room_day": 0, "hourly_rate": 0, "ancillary_rate": 0, "online_share": 0.8},
    "public_costs": {"ota_commission_rate": 0.1, "traffic_rate": 0, "mystery_shopper_kol_rate": 0, "offline_promotion_rate": 0, "ota_performance_monthly": 0, "turnover_tax_rate": 0.06},
    "jwl": {"capex": {}, "opex_monthly": {}, "replacement": {"year": 3}},
    "owner": {"capex": {}, "incremental_opex_monthly": {}, "allocated_opex_monthly": {}},
    "finance": {"discount_rate": 0.1, "hurdle_irr": 0.2, "maximum_discounted_payback_years": 3, "exit_occ_safety_buffer": 0.1}
  }
}
```

这是仅财务预评估的最小统一请求。需要竞品、HTML 或 Bitable 交付时，必须把
`collect_market_evidence.py --format skill-patch` 返回的三个字段**原样**合并：

```json
{
  "project_input": {"...": "validated finance input"},
  "market_evidence": {"...": "exact collection receipt"},
  "competitor_analysis": {"...": "exact embedded receipt field"},
  "competitor_report": {"...": "exact embedded receipt field"}
}
```

不要手工构造或修改后两项：`run.py` 会校验它们与 `market_evidence` 完全相同。OTA
二阶段还要求在采集时原样携带地图回执的 `candidate_pool`；完整示例见
`market-evidence-collection.md`。

Use the repository-only `sample-predeal-hotel.json` for a complete working
financial example during development. Samples and tests are intentionally
excluded from the published package; use `benchmark-defaults.json` only for
explicitly disclosed defaults.

`competitor_report` 服务于 `--format html` 和 `--format bitable` 的图文交付。
它可按正式竞品 `provider_place_id` 关联来源记录、装修观察及选定图片，并在视觉
对标区或“竞品报价与视觉证据”表中与该竞品的机位和同条件报价集中展示；不属于
财务输入，不能影响竞品分类、ADR 或投资测算。候选的可选 `market_profile` 仅补充
历史市场调研字段（等级、装修、房量、设施、评分等），同样不参与计算。完整字段
与图片约束见 `schemas/skill-request.schema.json`；Base 写入规则见
`references/bitable-delivery.md`。
