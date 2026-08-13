# 页面市场证据采集契约

`scripts/collect_market_evidence.py` 是与测算 Skill 配套的无界面 Host Tool。
它以 `market-evidence-collection/v1` 作为正式业务契约：任何 Agent 平台只需
调用 CLI 或本地 HTTP，不依赖 Codex Computer Use。

## 输入

```json
{
  "contract_version": "market-evidence-collection/v1",
  "target": {
    "name": "笨酒店",
    "address": "成都市成华区望平街滨河路6号",
    "city_id": "510100"
  },
  "search": {
    "provider_profile": "360-map-v1",
    "query": "电竞酒店",
    "radius_meters": 2000,
    "max_candidates": 200,
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
页面/图片请求的 URL、HTTP 状态和时间。它负责**全量 2km 空间候选**，再按距离
生成有限的价格/视觉标杆集，不要求每家泛候选都有图片或实时价格。安装一次运行时
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

## 完成条件与价格纪律

输出包含五个独立覆盖度：`candidates`、`benchmark_set`、`room_types`、`images`、`pricing`。
只有所有用户要求的维度完成，结果才是 `status=complete`，并允许 Skill 把
`competitor_analysis.collection_status` 标记为 `complete`。

当前 `360-map-v1` 能采集目标点、2km 候选、公开房型名称和标杆公开房图；它不会把
地图列表价当成房价。因为缺少与 `pricing_context` 完全一致的入住日、晚数、人数、
币种和可订状态，该 Profile 会返回 `pricing=not_collected` 与 `status=partial`。
这会让测算 Skill 保持 `pre_evaluation_only`，而不是生成伪 ADR。

`ctrip-hotel-v1` 是 macOS 上的 Ego Lite Profile。它以全量地图结果传入的
`candidate_inventory` 为边界，只处理 `benchmark_selected: true` 且已有显式
`ota_property` 映射的标杆；不会根据名称猜 OTA 房源。未登录显示“登录看低价”时
返回 `partial`，请先在 Ego Lite 登录批准的 OTA 后重跑。完整 Mac Mini/Hermes
预检、安装提示和两阶段请求见 `market-evidence-runtime.md`。

在已登录且页面回显统一 `pricing_context` 后，Ego Profile 会将详情页可见的房型、可订状态、
最终展示价、取消文案记录为 **P1 `pricing_observations`**，并仅选择酒店/房型图库图片（不会把
账户头像、Logo 或二维码写入竞品视觉证据）。P1 会出现在 HTML 与飞书多维表格，便于人工比价和
装修对标；但 Ego Profile 不读取 Network 载荷，也不猜测税费口径或机位数，故 P1 始终
`adr_eligible: false`，不得进入财务 ADR。

实时报价 Profile 必须为每条 `room_offers` 同时记录：正式竞品的 provider ID、OTA
房源/房型 ID、房型、机位数、可订状态、每晚含税/取消口径价格、完全相同的
`pricing_context`、来源 URL 和带时区采集时间。缺任一项的页面价格只能作为原始
观察，不能进入 ADR 中位数或财务输入。

`ctrip-live-rates-v1` 是携程实时价的生产 Profile。它需要 Chrome 中独立的
`ctrip-price-worker` Profile、人工完成的携程登录、Ui.Vision 与 OpenCLI Browser
Bridge。Ui.Vision 是**唯一**页面动作执行者；OpenCLI 只绑定同一标签页，读取动作前后
的 Network 与 DOM。系统不读取 Cookie、请求头、令牌或原始 Network body。若没有显式
`ota_property`，它只通过 `opencli ctrip search` 的唯一精确名称结果创建映射；多个或零个
结果均返回 `HOTEL_MAPPING_AMBIGUOUS`，不猜测。

该 Profile 把真实页面所见的 P1/P2/P3 记录为 `pricing_observations`，供 HTML 与飞书
展示；只有 P2 同时满足完全相同的报价条件、Network/DOM 价格一致、可订、税费、取消
政策及机位数时，才另写入严格的 `room_offers` 并可参与 ADR。`NO_INVENTORY` 是已完成的
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
