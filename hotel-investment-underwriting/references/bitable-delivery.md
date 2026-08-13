# Feishu Bitable delivery

`--format bitable` emits a portable JSON **delivery manifest** after the same
2km analysis and deterministic financial calculation. It is not a second
financial model and it does not call Feishu, retain credentials, or write a
database. An authorised Feishu host applies the manifest to a standard Base.

## Standard template

| Table | Delivery content |
|---|---|
| `项目测算总表` | One traceable project run: conclusion scope, 2km status, first-year result, two-party returns, month-level payback and risks. |
| `输入参数与来源` | Every merged financial input path, value, default/project-source marker and evidence metadata. |
| `投资与成本明细` | JWL/owner CapEx, equipment replacement and annual cash OpEx. |
| `年度收入与现金流` | Full annual revenue, public costs, sharing, cash flow and traditional-room comparison schedule. |
| `情景与敏感性` | Existing scenario and sensitivity outputs. |
| `房型配置` | Existing room-type mix, workstation count, ADR/RevPAR/OCC and traditional baseline fields. |
| `2km竞品` | Formal and excluded candidates, distance, source facts and optional market-profile facts. |
| `竞品报价与视觉证据` | Formal-competitor offers, shared pricing context, renovation observations and selected room-image evidence. |

The Base uses values, text, select, attachment and record-link fields only.
It deliberately has no formula or lookup field: `calculate.py` remains the
only finance/calculation owner.

It carries forward the useful field families from the historic Zhijing Excel
workbooks without copying their sheet formulas: `竞品调研` becomes `2km竞品` plus
`竞品报价与视觉证据`; `房型配置表` becomes `房型配置`; `运营分析` and `投资回报表`
become the summary, cost and annual-cash-flow tables; V3's inputs, scenarios
and sensitivities become separate traceable tables. Deprecated worksheet
layout, manually edited formula cells and client-specific columns are not part
of the standard template.

`competitor_analysis.candidates[].market_profile` is optional delivery
metadata for the historical market-research fields: Meituan badge, opening or
renovation, room count, image quality, facilities, product features, rating,
review count and surroundings. It is neither a 2km-classification fact nor a
financial input. Its exact validation rules are in
`schemas/skill-request.schema.json`.

## Host apply contract

1. Create the eight tables once in `manifest.template.tables` order, or verify
   an existing standard template by table name, record-key field and field
   names. This lets the two record-link fields resolve their target tables.
2. For each `manifest.records[table]`, find by the table's `record_key_field`;
   create when absent and patch when present. The same `input_sha256` therefore
   remains idempotent; a changed request creates a new `项目运行ID`.
3. After all records exist, resolve the logical keys in `manifest.links` to
   Feishu record IDs and write the link cells.
4. For each `manifest.attachments` item, upload only its supplied
   `data_uri` to the named attachment field. Do not download `source_url` or
   treat it as an image payload; it is a traceability link only. After a
   successful upload, set `附件状态` to `status_after_upload`.

The host must use the user or service identity explicitly authorised for that
Base. The manifest has no Base token, user ID, credential, access policy or
remote image-fetch capability.

## Command

```bash
python3 scripts/run.py --input /path/to/skill-request.json \
  --defaults references/benchmark-defaults.json \
  --format bitable > /path/to/bitable-delivery.json
```

Read the overall `conclusion_scope` and the `项目测算总表.结论范围` before
presenting the result. `pre_evaluation_only` is carried into the Base exactly
as returned; a Bitable export cannot turn incomplete 2km evidence into a
completed competitor conclusion.
