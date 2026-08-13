# 单一 Skill 数据契约

## 请求

公开契约分为两段：先由 `market-evidence-collection/v2` 采集页面证据，再把它
的 `skill-patch` 合并进唯一的测算请求
`hotel-investment-underwriting/schemas/skill-request.schema.json`。

| 区块 | 用途 | 权威来源 |
|---|---|---|
| 页面采集请求 | 地址、2km范围、房态报价口径与必需证据维度 | 宿主 Agent / 用户确认 |
| 页面采集回执 | 引擎、Profile、页面 URL/HTTP 状态、采集时间、全量候选/标杆集/房型/图片/报价覆盖度 | Playwright、Ego Lite、Ui.Vision+OpenCLI、Kimi WebBridge、crawl4ai、xcrawl 或 OpenCLI 的显式 Profile |
| `project_input` | 合同、房型、收入、成本和财务假设 | 项目团队、合同、报价、经确认的经营资料 |
| `competitor_analysis.confirmed_location` | 2km 分析中心 | 已授权地图能力 |
| `competitor_analysis.candidates` | 电竞竞品候选与报价观察 | 已授权地图/证据采集或人工核验 |
| `competitor_analysis.collection_status` | 候选集是否已完成定义内的采集 | 执行采集的宿主 |
| `spatial_collection` / OTA 请求的 `candidate_pool` | 地图阶段完成的精确 2km 候选集合（中心、来源 Profile、数量及排序地点 ID SHA-256） | 地图 Profile；OTA Profile 只能原样回传 |
| `competitor_analysis.pricing_context` | 同批报价的入住日期、晚数、人数和币种 | 已授权报价采集或人工核验 |
| `competitor_analysis.candidates[].market_profile` | 可选历史市场调研事实：等级、装修、房量、设施、评分等；仅用于交付展示 | 已授权公开资料或人工核验 |
| `competitor_report` | 可选的竞品装修观察、图片和报告标题；用于 HTML 和 Bitable 的视觉对标展示 | 已授权公开资料或人工核验 |

金额单位为人民币元；比例使用小数；ADR 为元/已售房夜；距离由 Skill 计算为米。

## 页面采集业务契约

`schemas/market-evidence-collection.schema.json` 与
`scripts/market_evidence_contract.py` 是页面采集的权威输入校验。输出必须包含：

- `collector.engine`（仅 `playwright`、`ego-browser`、`ctrip-live-rates`、`kimi-webbridge`、`crawl4ai`、`xcrawl` 或 `opencli`）、引擎版本、Profile、开始/结束时间和实际页面/图片 URL 的 HTTP 回执；
- 已确认的 `target_resolution`，或明确的歧义/失败；不能以名称相近自动替换物业；
- `candidates`、`benchmark_set`、`room_types`、`images`、`pricing` 五项独立覆盖度；
- 对 OTA Profile：已完成的 `candidate_pool`，以及结果中与其逐字相同的 `spatial_collection`；`collect_market_evidence.py` 还会校验返回的引擎、Profile 和中心点与请求一致；
- 可合并的 `market_evidence`、`competitor_analysis` 和 `competitor_report`。采集器没有 `project_input`，也不能计算投资结论；`run.py` 会拒绝与回执不一致的两块竞品证据。

`collection_result.status=complete` 只有在五项覆盖度全部 `complete` 时才合法。它是
**全证据回执状态**。`competitor_analysis.collection_status` 和
`spatial_collection.status` 是另一条、仅表示**全量 2km 空间候选池**的状态：地图已穷尽、
中心/来源/候选指纹都匹配时可以为 `complete`，即使 OTA 的图片或价格覆盖仍是
`partial`。因此页面结构改变、登录失效、验证码、限流或来源错误必须仍以
`collection_gaps`/`collection_issues` 可见；它们会阻止 ADR 和完整交付，却不能抹掉
已经可审计的空间竞品结论。

内置 Profile 不能互相冒充：`playwright` 只能声明 `360-map-v1`，`ego-browser` 只能声明
`ctrip-hotel-v1`，`ctrip-live-rates` 只能声明 `ctrip-live-rates-v1`。可替换外部引擎仍须在
请求和回执中使用完全相同的显式 Profile；任何错配都在合并前失败。

## 最小竞品事实

每个候选需要：

- 与 `confirmed_location.provider` 完全一致的 `provider`、`provider_place_id`、`coordinate_system: "GCJ-02"`、GCJ-02 `longitude`/`latitude`；
- 对住宿候选提供 `property_kind`、`esports_positioning`、`operating_status`；已确认非住宿场所只需 `property_kind: "non_lodging"`，无需虚构酒店经营或电竞定位；
- `source_platform`、`source_url`、`observed_at`、`confidence`；
- 进入价格/视觉标杆前，OTA 请求必须携带完整地图实体和已完成的 `candidate_pool`。`ctrip-hotel-v1` 还要求显式 `ota_property`（平台、稳定 OTA 房源 ID、页面 URL、匹配方式和匹配时间）；`ctrip-live-rates-v1` 仅可在**名称唯一精确且 `target.address` 解析出的城市也唯一匹配**时创建该映射。任何其他情况都返回 `HOTEL_MAPPING_AMBIGUOUS`，不得按名称猜测；
- 如需 ADR 参考，`room_offers` 同时必须含 `room_type_provider_id`、`workstations`、`nightly_price`、`availability: "available"`、`currency: "CNY"`、`tax_included`、`cancellation_policy`、逐条 `pricing_context`、`source_url` 和带时区 `observed_at`。页面 Profile 必须以完全相同的入住条件取得可订状态和报价；地图/列表展示价、不同日期价或未说明房态的金额只能保留为原始观察，不能写入 ADR 样本。同一物业的多个同机位报价归并为该物业的中位数，不可充当多个样本。

Skill 使用未舍入 Haversine 距离判断 `0 <= distance_meters <= 2000`。只有主营电竞住宿、营业中且证据完整的候选可成为 `pure_esports_hotel`；普通酒店附带电竞房标为 `incidental_esports_rooms`，已知非住宿/停业对象分别标为 `excluded_non_lodging` / `excluded_not_operating`，并都不进入正式竞品。

候选的 `provider_place_id` 在一次请求中必须唯一。`low` 置信度的来源仍保留在竞品清单中，但不计入 ADR；每个机位须有至少三家独立的 `medium` 或 `high` 置信度物业才可给出建议 ADR。`observed_at` 由宿主的证据采集有效期策略审核；过期报价必须重新采集，Skill 不擅自设定业务时效阈值。

## 可选视觉展示证据

`competitor_report.candidate_media[]` 必须通过已被结果确认的正式
`pure_esports_hotel` 的 `provider_place_id` 绑定。每条可包含一段有 `observation_source_url` 的装修观察，以及最多 4 张带 `caption`、`source_url`、采集时间、MIME 和 SHA-256 的 JPEG、PNG 或 WebP 图片。图片必须使用 `data:image/...;base64,...`；HTML 渲染器拒绝远程图片地址、SVG、未知字段、错误 hash 和不匹配的图片字节。报告会在“视觉竞品对标”区把每条视觉证据与该竞品的距离、房型、机位和同条件报价集中呈现。这样 HTML 本身没有外部图片、脚本或样式依赖，来源 URL 只作为可点击的追溯记录。

展示证据只辅助人工比较装修与产品状态，不进入正式竞品分类、ADR 样本或财务模型，也不自动写入调价结论。若 `provider_place_id` 不在本次正式竞品集合内，HTML 或 Bitable 输出快速失败，避免生成孤立、错绑或未展示的图片；JSON 和 Feishu 摘要的核心投测仍可独立运行。

## 输出

`scripts/run.py` 返回：

- `competitor_analysis`：候选数、正式竞品、排除原因、已标准化的 `pricing_context`、按机位的 ADR 参考及缺失项；每个机位结果含计入样本数和 `low_confidence_excluded_property_count`。未满足完整采集、统一报价条件或三家中/高置信度样本时，所有聚合 ADR 字段均为 `null`；候选原始报价仍保留以供补证；
- `financial_result`：原有确定性财务输出，并附带与顶层一致的 `conclusion_scope`。`base_case.jwl`、`owner_incremental`、`owner_fully_loaded`（以及已启用时的 `owner_economic_incremental`）均含 `first_year_average_monthly_operating_net_cashflow`、`static_payback_months`、`static_payback_months_rounded_up`、`discounted_payback_months` 与 `discounted_payback_months_rounded_up`；
- `workflow`：`ready_for_review`（空间竞品池已完成）或 `pre_evaluation_only`（空间证据未完成），以及不自动写入财务 ADR 的说明；OTA 的 `partial` 仍会在 conditions 中保留，并令相应机位 ADR 为空；
- `conclusion_scope`：宿主必须读取的整体结论范围；只有 2km 空间证据未完成时为 `pre_evaluation_only`；
- `input_sha256`、`defaults_sha256` 和 `skill_version`：轻量追溯字段；后者来自发布包内的 `VERSION`。

选择 `--format html` 时，标准输出是一份独立的竞品调研 HTML：含 2km 范围、完成状态、正式竞品房型/报价、可选装修观察与图片形成的视觉竞品对标区、ADR 表、排除候选、核心结果已计算的投资回报与按月回本表，以及与投资测算的衔接。`pre_evaluation_only` 会在报告中显式保留，不能被渲染成正式竞品结论。

选择 `--format bitable` 时，标准输出是一份 Feishu Bitable 交付清单。它含模板、按逻辑记录键组织的八张表记录、待解析的记录关联以及待上传的内嵌图片字节；不含 Base token、用户身份、API 调用、公式或远程抓取规则。`项目测算总表.结论范围` 保留与 `conclusion_scope` 相同的值。完整模板与宿主写入顺序见 `references/bitable-delivery.md`。

不要将竞品建议自动写入 `project_input`。由业务审核人明确选择 ADR/OCC/房型假设后再重新运行。

`static_payback_months` 沿用历史投资表“回款周期/月”口径：一次性初投 ÷ 首年平均月经营净现金，不含后续设备重置和末期残值。`*_rounded_up` 是给业务交付的保守整月数；原始月数保留用于审计。`discounted_payback_months` 只将既有年度折现持续回收期按 12 个月/年呈现，仍以其年度现金流、重置和折现口径为准。

## 不属于该契约的内容

项目修订号、审批事件、运行归档、原始页面正文/完整响应、供应商密钥、任务授权和施工状态不是测算 Skill 输入或输出。页面采集的最小回执与规范化证据属于发布包契约；原始抓取内容和凭证仍由宿主单独管理。
