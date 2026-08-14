# 页面市场证据采集契约

`scripts/collect_market_evidence.py` 是与测算 Skill 配套的无界面 Host Tool。
它以 `market-evidence-collection/v2` 作为正式业务契约：任何 Agent 平台只需
调用 CLI 或本地 HTTP，不依赖 Codex Computer Use。

## 信任边界

采集器结构校验通过后，必须由部署宿主以环境变量
MARKET_EVIDENCE_RECEIPT_HMAC_KEY 签发 HMAC 回执。run.py 只接受当前宿主密钥可验证的
回执；Agent 不能手写或修改 market_evidence 来注入竞品、图片或 ADR。密钥至少 32 字节，
只放在 Hermes/macOS 服务配置中，绝不放进 JSON、HTML、飞书清单、日志或 Git。

collector.page_sources 的 status 是实际 HTTP 响应才可写入的值。仅能控制浏览器标签而不能取得
响应对象时，采集器写入 status=null 与 status_observed=false；不得用 200 或 599 猜测页面状态。

## 输入

```json
{
  "contract_version": "market-evidence-collection/v2",
  "target": {
    "name": "笨酒店",
    "address": "成都市成华区望平街滨河路6号",
    "city_id": "510100"
  },
  "search": {
    "provider_profile": "360-map-v1",
    "query": "电竞酒店",
    "radius_meters": 2000,
    "max_candidates": 1000,
    "max_benchmark_candidates": 8,
    "max_images_per_candidate": 1
  },
  "pricing_context": {
    "check_in_date": "2026-08-20",
    "nights": 1,
    "guests": 2,
    "currency": "CNY"
  },
  "required_evidence": {"benchmark_set": true, "room_types": true, "images": true, "pricing": true}
}
```

若目标名称有歧义，先在 `target.center` 填入同源 `provider_place_id` 和确认的
GCJ-02 中心点；采集器不能把同名物业猜成精确点位。

## 运行时与引擎

默认 Profile 是 `360-map-v1`，以无头 Playwright 打开页面来源，保留每一次
页面/图片请求的 URL、HTTP 状态和时间。它负责**全量 2km 空间候选**，再从其中按
住宿发现词组（酒店、民宿、客栈、公寓及电竞住宿变体）先建立可审计的候选池；再按
公开房图、房型披露、评分/点评信号、距离的固定顺序，从主营电竞住宿生成有限的价格/视觉标杆集；标杆
**最多 8 家**，不要求每家泛候选都有图片或实时价格。安装一次运行时
后即可供 Hermes、OpenAI Agent 或任意本地进程调用：

```bash
cd hotel-investment-underwriting/collector
npm ci
npx playwright install chromium

python3 ../scripts/collect_market_evidence.py \
  --input /path/to/collection-request.json \
  --format skill-patch > /path/to/market-evidence-patch.json
```

`--serve 127.0.0.1:8791` 提供 `POST /v1/collect` 和
`POST /v1/collect/skill-patch`。服务只监听本机，不保存请求、凭证或客户资料。

Ego Lite、Ui.Vision+OpenCLI、Kimi WebBridge、crawl4ai、xcrawl、OpenCLI 是同等的正式页面采集引擎，不是
模型的隐式能力。宿主选择其中一个时，设置对应命令环境变量；命令接收本契约 JSON
的 stdin，并返回同一份结果 JSON：

| 引擎 | 环境变量 |
|---|---|
| Ego Lite | 内置 `ego-browser` / `ctrip-hotel-v1`（无环境变量） |
| Ui.Vision + OpenCLI | 内置 `ctrip-live-rates` / `ctrip-live-rates-v1`（无环境变量） |
| Kimi WebBridge | `MARKET_EVIDENCE_KIMI_WEBBRIDGE_COMMAND` |
| crawl4ai | `MARKET_EVIDENCE_CRAWL4AI_COMMAND` |
| xcrawl | `MARKET_EVIDENCE_XCRAWL_COMMAND` |
| OpenCLI | `MARKET_EVIDENCE_OPENCLI_COMMAND` |

未配置时命令必须失败，绝不偷偷切换来源或伪造数据。每个生产 Profile 都要在其
来源页面/网络响应变更后重新验收，并保留 `collector.page_sources` 回执。

`max_benchmark_candidates` 的默认值与硬上限都是 `8`。它只限制进入 OTA 价格、房型和
图片深度调研的标杆数，绝不截断 2km 候选池；若页面候选数超过 `max_candidates`，结果
必须标记为 `partial`，而不是悄悄遗漏候选。
`max_candidates` 默认且最高为 1,000，是传输安全上限，不是标杆数量；超过它必须由
采集器明确返回未完成的空间候选池，不能产出“全量 2km”结论。

地图结果中的 `spatial_collection` 是二阶段的不可变交接件：包含完整状态、地图引擎/
Profile、确认中心、全量候选数、按排序 provider-place-ID 的 SHA-256，以及候选不可变事实
快照的 SHA-256（坐标、分类、运营状态、来源）。OTA 请求必须
将它原样放入 `candidate_pool`，同时仍携带**全量** `candidate_inventory`；OTA 结果再原样
回传为 `spatial_collection`。CLI 会拒绝任一引擎、Profile、中心、数量或指纹不一致的回执。
这避免只传入已选 8 家标杆后，把不完整 2km 集合误称为完整。

## 完成条件与价格纪律

输出包含五个独立覆盖度：`candidates`、`benchmark_set`、`room_types`、`images`、`pricing`。
只有所有用户要求的维度完成，**采集回执**才是 `status=complete`。但
`competitor_analysis.collection_status` 只表达全量 2km 空间候选是否完成：当候选池未被
截断、坐标/来源完整时，它可以为 `complete`，即使后续 OTA 报价回执仍是 `partial`。
这会保留已核验的竞品、房型和房图；`pricing=partial` 仍严格阻止任何 ADR 推导。

当前 `360-map-v1` 能采集目标点、2km 候选、公开房型名称和标杆公开房图；它不会把
地图列表价当成房价。因为缺少与 `pricing_context` 完全一致的入住日、晚数、人数、
币种和可订状态，该 Profile 会返回 `pricing=not_collected` 与 `status=partial`。
它不会生成伪 ADR；若 2km 空间候选已完整，Skill 仍可输出待人工确认目标 ADR 的
`ready_for_review`，但绝不会把地图列表价写入财务输入。

`ctrip-hotel-v1` 是 macOS/Mac Mini 上的 **默认** Ego Lite OTA Profile。它以全量地图结果传入的
`candidate_inventory` 为边界，只处理 `benchmark_selected: true` 且已有显式
`ota_property` 映射的标杆；不会根据名称猜 OTA 房源。未登录显示“登录看低价”时
返回 `partial`，请先在 Ego Lite 登录批准的 OTA 后重跑。完整 Mac Mini/Hermes
预检、安装提示和两阶段请求见 `market-evidence-runtime.md`。

在已登录且页面回显统一 `pricing_context` 后，Ego Profile 会将详情页可见的房型、可订状态、
最终展示价、取消文案记录为 **P1 `pricing_observations`**，并仅选择酒店/房型图库图片（不会把
账户头像、Logo 或二维码写入竞品视觉证据）。P1 会出现在 HTML 与飞书多维表格，便于人工比价和
装修对标；但 Ego Profile 不读取 Network 载荷，也不猜测税费口径或机位数，故 P1 始终
`adr_eligible: false`，不得进入财务 ADR。页面明确显示“无可订房”“售罄”或“不接受预订”时，
Ego 返回非重试 `NO_INVENTORY`：这是一条完成的负向价格结果，保留已取得的房型/图片与页面来源，
但不会拿附近酒店列表价代替该竞品价格。

当详情页存在结构化可订房型卡片时，Ego 同时保留 `room_type_evidence`：这是房型名称、稳定房型
来源 ID、页面 URL 和带时区采集时间。它在“竞品报价与视觉证据”表以“房型观察”单独写入，在
HTML 的“已采集房型（非报价）”区展示；酒店介绍、特色、评论或附近列表里的“套房/电竞房”文字
绝不计为房型。发生 `NO_INVENTORY` 时，已有房型观察可交付；若 OTA 未展示结构化房型，则如实
返回房型待补，且不会被提升为 P1 价格或 ADR 样本。

实时报价 Profile 必须为每条 `room_offers` 同时记录：正式竞品的 provider ID、OTA
房源/房型 ID、房型、机位数、可订状态、每晚含税/取消口径价格、完全相同的
`pricing_context`、来源 URL 和带时区采集时间。缺任一项的页面价格只能作为原始
观察，不能进入 ADR 中位数或财务输入。

`ctrip-live-rates-v1` 是可选的携程 P2 强校验 Profile；默认 Ego 链路不依赖它。它需要 Chrome 中独立的
`ctrip-price-worker` Profile、人工完成的携程登录、Ui.Vision 与 OpenCLI Browser
Bridge。OpenCLI 当前一次只能可靠绑定**一个**已连接的 Browser Bridge Profile：必须只保留
`ctrip-price-worker` 启用该扩展并标为 default，其他 Chrome Profile 的该扩展须禁用；否则预检
返回 `action_required`，不会进入携程页面。Ui.Vision 是**唯一**页面动作执行者；OpenCLI 只绑定同一标签页，读取动作前后
的 Network 与 DOM。系统不读取 Cookie、请求头、令牌或原始 Network body。若没有显式
`ota_property`，它只通过 `opencli ctrip search` 的唯一精确名称结果创建映射；多个或零个
结果均返回 `HOTEL_MAPPING_AMBIGUOUS`，不猜测。自动映射还必须从 `target.address` 解析出
城市，并要求搜索返回同一城市；地址缺城市、城市缺失或不一致同样失败关闭。预检会执行
无页面副作用的 `opencli ctrip search --help`，使缺少该本机插件在上线前可见。

该 Profile 把真实页面所见的 P1/P2/P3 记录为 `pricing_observations`，供 HTML 与飞书
展示。Ui.Vision 采集后，OpenCLI 只读当前页面的受限房型 DOM 观察；包内 Scrapling
ctrip-dom-parser/v1 离线以 ctrip-element-registry/v1 解析它。该解析器不是浏览器或
第二采集源，不发请求、不读 Cookie，并且只接收受限的原始房型卡 outerHTML，不接收采集脚本
重建的语义字段；解析失败会产生 DOM_SCHEMA_DRIFT。只有 P2 同时
通过这一版本化 DOM 解析、完全相同的报价条件、Network/DOM 价格一致、可订、税费、取消
政策及机位数时，才另写入严格的 `room_offers` 并可参与 ADR。页面没有回显请求的日期和
人数时必记 `pricing_context_unverified`，即使 Network/DOM 数字相同也绝不能 ADR-eligible。
公开图片只从酒店/房型/图库上下文选择，过滤账号头像、Logo 与二维码；下载仅接受 HTTPS
批准 CDN、禁止重定向、限时并按声明与流式字节数限制。所有标杆共用总嵌入体积上限 7.5MB，
而非每家各自放大。NO_INVENTORY 是已完成的
负向采集结果，不以空表或虚构价格代替；`AUTH_REQUIRED`、`CAPTCHA_REQUIRED`、
`QUERY_MISMATCH`、`PRICE_MISMATCH`、`NETWORK_SCHEMA_DRIFT` 等以结构化
`collection_issues` 返回。

## 与测算 Skill 对接

`--format skill-patch` 返回采集回执及其严格绑定的两块证据：

```json
{"market_evidence": {"...": "..."}, "competitor_analysis": {"...": "..."}, "competitor_report": {"...": "..."}}
```

宿主把它与已验证的 `project_input` 合并后，仍只调用唯一测算入口
`scripts/run.py`。入口会重新校验 `market_evidence`，并拒绝被替换或不一致的
`competitor_analysis`/`competitor_report`。采集器不计算距离结论、ADR、回本期、
IRR 或 NPV；这些仍由 Skill 内代码决定。图片以受大小限制的 `data_uri` 返回，
并记录来源 URL、采集时间、MIME 和 SHA-256，因此 HTML 和飞书附件可以离线展示；
来源 URL 只用于追溯。
