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
| `2km竞品` | Formal and excluded candidates, distance, source facts, optional market-profile facts, plus deterministic deep-research benchmark rank/reason when selected. |
| `竞品报价与视觉证据` | Formal-competitor page room-type observations, offers, shared pricing context, renovation observations and selected room-image evidence. |

The Base uses values, text, select, attachment and record-link fields only.
It deliberately has no formula or lookup field: `calculate.py` remains the
only finance/calculation owner.

## Empty-table prevention and delivery gate

Manifest `1.2` never serializes the three decision-facing tabs as silent empty
arrays. Each now has `交付状态`; the project summary also has `交付完整性` and
`交付待补项`.

- A missing room mix creates one `待补房型` notice. It is explicitly labelled
  non-room data and carries no invented room count, ADR or OCC.
- Missing or incomplete 2km research creates one `待补2km竞品` notice. A complete
  search with zero formal competitors creates `检索完成无正式竞品`, which is a
  valid result rather than a missing-data condition.
- Every formal competitor without an embedded image creates one
  `待补视觉图片` notice bound to that competitor. No formal competitors creates
  one visible non-competitor visual notice instead of an empty evidence table.

The manifest's top-level `delivery_gate` is the evidence readiness decision for
these three tabs. The host must only present the run as a complete client
delivery when `delivery_gate.final_delivery_eligible` is `true` **and** its
post-write readback has changed the summary's `交付完整性` from `待写入核验` to
`可交付`. This prevents a failed attachment upload from being misreported as a
complete visual delivery. When the gate is false, the host may write the
manifest as a draft for traceability, but must preserve the gap rows and
`交付待补项`; it must not call the draft a completed research delivery.

For a positive gate, use `delivery_gate.expected_visual_attachment_count` and
`delivery_gate.post_write_completion` as deterministic host checks. The host
must match every manifest record key and link, and read back that many visual
attachment cells before setting the summary to `可交付`.

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

`competitor_analysis.candidates[].room_type_evidence` 是 OTA 页面已观察到的房型名称及其
来源 ID、URL、采集时间。它以“房型观察”记录写入 `竞品报价与视觉证据`，不包含价格、机位、
税费或可订承诺，也不参与 ADR 或财务模型。宿主迁移已有模板时必须保留 `证据类型` 的既有选项并
增补“房型观察”。

For the at-most-eight `benchmark_selected` competitors, the map Profile also
emits `benchmark_rank` and `benchmark_selection_reason`. These fields describe
the fixed public-evidence ordering (room photo, disclosed room types,
rating/reviews, distance, provider-ID tie break); they make it possible to
audit why a property received costly OTA/image research. They do not change
competitor classification, ADR eligibility or finance.

## Host apply contract

1. Create the eight tables once in `manifest.template.tables` order, or verify
   an existing standard template by table name, record-key field, field type
   and select options. For an older template, only add missing fields or add
   the missing select option while preserving all existing options; do not
   overwrite a field type or delete historical columns. This lets the two
   record-link fields resolve their target tables and prevents P1/OTA columns
   from being silently dropped.
2. For each `manifest.records[table]`, find by the table's `record_key_field`;
   create when absent and patch when present. The same `input_sha256` therefore
   remains idempotent; a changed request creates a new `项目运行ID`.
3. After all records exist, resolve the logical keys in `manifest.links` to
   Feishu record IDs and write the link cells.
4. For each `manifest.attachments` item, upload only its supplied
   `data_uri` to the named attachment field. Do not download `source_url` or
   treat it as an image payload; it is a traceability link only. After a
   successful upload, set `附件状态` to `status_after_upload`.
5. Before writing, verify or migrate the `1.2` fields: summary
   `交付完整性`/`交付待补项`, child-table `交付状态`, and the full
   `2km竞品` / `竞品报价与视觉证据` field definitions. After writeback, read every
   manifest record key, record-link and attachment count back. For an eligible manifest, only then update the
   summary from `待写入核验` to `可交付`; otherwise keep or set `待补证据` and state
   the failed/missing item. Do not mark the project complete when the manifest
   delivery gate is blocked.

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
