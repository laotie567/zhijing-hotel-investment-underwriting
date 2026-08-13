# 单一 Skill 数据契约

## 请求

唯一公开请求是 `hotel-investment-underwriting/schemas/skill-request.schema.json`。

| 区块 | 用途 | 权威来源 |
|---|---|---|
| `project_input` | 合同、房型、收入、成本和财务假设 | 项目团队、合同、报价、经确认的经营资料 |
| `competitor_analysis.confirmed_location` | 2km 分析中心 | 已授权地图能力 |
| `competitor_analysis.candidates` | 电竞竞品候选与报价观察 | 已授权地图/证据采集或人工核验 |
| `competitor_analysis.collection_status` | 候选集是否已完成定义内的采集 | 执行采集的宿主 |
| `competitor_analysis.pricing_context` | 同批报价的入住日期、晚数、人数和币种 | 已授权报价采集或人工核验 |
| `competitor_report` | 可选的竞品装修观察、图片和报告标题；用于 HTML 的视觉竞品对标展示 | 已授权公开资料或人工核验 |

金额单位为人民币元；比例使用小数；ADR 为元/已售房夜；距离由 Skill 计算为米。

## 最小竞品事实

每个候选需要：

- 与 `confirmed_location.provider` 完全一致的 `provider`、`provider_place_id`、`coordinate_system: "GCJ-02"`、GCJ-02 `longitude`/`latitude`；
- 对住宿候选提供 `property_kind`、`esports_positioning`、`operating_status`；已确认非住宿场所只需 `property_kind: "non_lodging"`，无需虚构酒店经营或电竞定位；
- `source_platform`、`source_url`、`observed_at`、`confidence`；
- 如需 ADR 参考，附带 `room_offers[].workstations` 和 `nightly_price`，并在请求顶层提供一个 `pricing_context`：`check_in_date`（`YYYY-MM-DD`）、正整数 `nights`、正整数 `guests` 和 `currency: "CNY"`。同一物业的多个同机位报价归并为该物业的中位数，不可充当多个样本。

Skill 使用未舍入 Haversine 距离判断 `0 <= distance_meters <= 2000`。只有主营电竞住宿、营业中且证据完整的候选可成为 `pure_esports_hotel`；普通酒店附带电竞房标为 `incidental_esports_rooms`，已知非住宿/停业对象分别标为 `excluded_non_lodging` / `excluded_not_operating`，并都不进入正式竞品。

候选的 `provider_place_id` 在一次请求中必须唯一。`low` 置信度的来源仍保留在竞品清单中，但不计入 ADR；每个机位须有至少三家独立的 `medium` 或 `high` 置信度物业才可给出建议 ADR。`observed_at` 由宿主的证据采集有效期策略审核；过期报价必须重新采集，Skill 不擅自设定业务时效阈值。

## 可选 HTML 展示证据

`competitor_report.candidate_media[]` 必须通过已被结果确认的正式
`pure_esports_hotel` 的 `provider_place_id` 绑定。每条可包含一段有 `observation_source_url` 的装修观察，以及最多 4 张带 `caption` 和 `source_url` 的 JPEG、PNG 或 WebP 图片。图片必须使用 `data:image/...;base64,...`；HTML 渲染器拒绝远程图片地址、SVG、未知字段和不匹配的图片字节。报告会在“视觉竞品对标”区把每条视觉证据与该竞品的距离、房型、机位和同条件报价集中呈现。这样 HTML 本身没有外部图片、脚本或样式依赖，来源 URL 只作为可点击的追溯记录。

展示证据只辅助人工比较装修与产品状态，不进入正式竞品分类、ADR 样本或财务模型，也不自动写入调价结论。若 `provider_place_id` 不在本次正式竞品集合内，HTML 输出快速失败，避免生成孤立、错绑或未展示的图片；JSON 和 Feishu 的核心投测仍可独立运行。

## 输出

`scripts/run.py` 返回：

- `competitor_analysis`：候选数、正式竞品、排除原因、已标准化的 `pricing_context`、按机位的 ADR 参考及缺失项；每个机位结果含计入样本数和 `low_confidence_excluded_property_count`。未满足完整采集、统一报价条件或三家中/高置信度样本时，所有聚合 ADR 字段均为 `null`；候选原始报价仍保留以供补证；
- `financial_result`：原有确定性财务输出，并附带与顶层一致的 `conclusion_scope`。`base_case.jwl`、`owner_incremental`、`owner_fully_loaded`（以及已启用时的 `owner_economic_incremental`）均含 `first_year_average_monthly_operating_net_cashflow`、`static_payback_months`、`static_payback_months_rounded_up`、`discounted_payback_months` 与 `discounted_payback_months_rounded_up`；
- `workflow`：`ready_for_review` 或 `pre_evaluation_only`，以及不自动写入财务 ADR 的说明；
- `conclusion_scope`：宿主必须读取的整体结论范围；竞品未完成时为 `pre_evaluation_only`；
- `input_sha256`、`defaults_sha256` 和 `skill_version`：轻量追溯字段；后者来自发布包内的 `VERSION`。

选择 `--format html` 时，标准输出是一份独立的竞品调研 HTML：含 2km 范围、完成状态、正式竞品房型/报价、可选装修观察与图片形成的视觉竞品对标区、ADR 表、排除候选、核心结果已计算的投资回报与按月回本表，以及与投资测算的衔接。`pre_evaluation_only` 会在报告中显式保留，不能被渲染成正式竞品结论。

不要将竞品建议自动写入 `project_input`。由业务审核人明确选择 ADR/OCC/房型假设后再重新运行。

`static_payback_months` 沿用历史投资表“回款周期/月”口径：一次性初投 ÷ 首年平均月经营净现金，不含后续设备重置和末期残值。`*_rounded_up` 是给业务交付的保守整月数；原始月数保留用于审计。`discounted_payback_months` 只将既有年度折现持续回收期按 12 个月/年呈现，仍以其年度现金流、重置和折现口径为准。

## 不属于该契约的内容

项目修订号、审批事件、运行归档、爬虫请求/响应、供应商密钥、任务授权和施工状态不是 Skill 输入或输出。它们不在当前仓库或发布包中；如有需要，由宿主单独管理。
