# 页面采集运行时与 Mac Mini 部署

`scripts/collect_market_evidence.py` 是唯一的本机 CLI/HTTP 接口。它不依赖
Codex Computer Use；Hermes、OpenAI Agent 或其他宿主只需调用该命令或其仅本机
监听的 `/v1/collect`、`/v1/collect/skill-patch` HTTP 端点。

## 先做预检

在新 Mac Mini 的仓库根目录执行：

```bash
python3 hotel-investment-underwriting/scripts/collect_market_evidence.py \
  --preflight --all-engines
```

输出的 `state` 只有 `ready` 才可运行相应引擎。`action_required` 必须按
`install_hint` 安装或配置；工具不会切换到另一来源、更不会填造证据。

| 引擎/Profile | 适用证据 | Mac Mini 预检与动作 |
|---|---|---|
| `playwright` / `360-map-v1` | 2km 全量地图候选、公开房型/图片 | 在 `collector/` 执行 `npm ci && npx playwright install chromium`。 |
| `ego-browser` / `ctrip-hotel-v1` | 已登录 OTA 的房型、可订状态、同条件 **P1 页面价格**、酒店/房型图片 | 安装 **Ego Lite**（不是 Eagle），确认 `ego-browser` 命令可用；在 Ego Lite 登录获授权 OTA 后重跑。P1 会交付到 HTML/Base，但不进入 ADR。安装指南：<https://lite.ego.app/document/zh/docs/quick-start>。 |
| `ctrip-live-rates` / `ctrip-live-rates-v1` | 携程 P1/P2 页面价格、库存、房型、公开图片与 Network/DOM 双证据 | 安装 Google Chrome、OpenCLI Browser Bridge、Ui.Vision 与 `uivision-mcp-bridge@1.1.1`；创建专用 `ctrip-price-worker` Profile 并人工登录携程、完成 Ui.Vision 本机配对。 |
| `kimi-webbridge` | 真实浏览器会话的替代页面适配器 | 安装并连接 Kimi WebBridge 浏览器扩展，设置 `MARKET_EVIDENCE_KIMI_WEBBRIDGE_COMMAND`。若预检提示缺失，按 <https://kimi.com/features/webbridge> 安装/连接。 |
| `crawl4ai` / `xcrawl` / `opencli` | 经批准的静态页、检索或补采适配器 | 安装批准实现，并设置相应 `MARKET_EVIDENCE_*_COMMAND`。 |

预检不安装软件、不读取 Cookie、不打开页面。Hermes 应在首次部署、升级浏览器/扩展
或 Profile 后主动运行一次，并把 `install_hint` 原样展示给管理员。

## 受控的两阶段采集

1. 用 `360-map-v1` 建立 **全量 2km 候选集**。它对每家候选保留同源地图实体、坐标
   和来源，再按公开房图、房型披露、评分/点评信号和距离的固定顺序选出
   `benchmark_selected` 标杆，**最多 8 家**；不要求所有泛候选都有图片或价格。
2. 将全量候选放进 `candidate_inventory`。`ctrip-hotel-v1` 仍要求每个选中标杆先写入
   经页面确认的 `ota_property` 映射；`ctrip-live-rates-v1` 可以仅对唯一精确的
   `opencli ctrip search` 结果、且酒店地址与搜索结果城市一致时自动建立映射。把地图回执
   的 `spatial_collection` 原样作为 `candidate_pool` 一并传入；随后用 `ego-browser` 或
   `ctrip-live-rates` 分别运行对应 Profile。

`ota_property` 必须包含 `platform`、稳定 `property_id`、详情页 URL、匹配方式和
带时区匹配时间。它是“地图实体 ↔ OTA 房源”的显式桥梁，不能凭名称猜测。`ctrip-hotel-v1`
会以 `property_id` 构造携程 PC 详情页的 `checkIn`/`checkOut`/`adult` URL，并从渲染
页面复核日期、晚数和成人数。映射可以
由已配置的 Kimi WebBridge/crawl4ai/xcrawl/OpenCLI 页面适配器建立，但必须回传同一
字段。

`ctrip-hotel-v1` 在页面同时回显房型、可订、最终展示价、取消文案和完全相同的
`pricing_context` 时，写入 P1 `pricing_observations`。P1 是真实的 DOM 页面证据，但该
Profile 不读取 Network 载荷，也不猜测税费口径或机位数，因此永远不写入 `room_offers` 或
ADR。未登录显示“登录看低价”、验证码、售罄或页面字段缺失都会产生 `partial`；不会用列表价替代。

### 携程实时价 Worker

在 `ctrip-price-worker` Chrome Profile 中只安装并启用 OpenCLI Browser Bridge 和
Ui.Vision。携程账户由管理员在这个 Profile 内正常登录；Skill、Hermes 与任何 Agent
都不接收密码、Cookie 或验证码。然后安装固定版本 Bridge：

```bash
npm install -g uivision-mcp-bridge@1.1.1
python3 scripts/collect_market_evidence.py --preflight --engine ctrip-live-rates
```

首次配对时，管理员按 Ui.Vision 本机设置完成 MCP Bridge 的 `127.0.0.1` 配对，并保持
侧边栏开启。采集器为单任务 Worker：临时互斥锁防止两个 Hermes 任务同时操作同一
浏览器页面；锁在任务退出后删除，记录进程已不存在时才自动回收；只有没有有效 PID 的
异常锁才按 12 分钟过期回收，不保存项目状态。预检同时检查无副作用的
`opencli ctrip search --help`，保证自动映射
插件可用。Ui.Vision 运行仓库内固定的刷新宏，
OpenCLI 仅执行 `bind`、`network` 与只读 `eval`。若 Ui.Vision 未配对、携程未登录、验证码
出现或报价条件未回显，返回结构化失败原因，绝不回退到 Playwright、Ego Lite 或列表价。

## Hermes 调用

Hermes 只需在 Skill 目录内调用：

```bash
python3 scripts/collect_market_evidence.py \
  --engine playwright --input /path/to/360-request.json --format skill-patch

python3 scripts/collect_market_evidence.py \
  --engine ego-browser --input /path/to/ctrip-request.json --format skill-patch

python3 scripts/collect_market_evidence.py \
  --engine ctrip-live-rates --input /path/to/ctrip-live-request.json --format skill-patch
```

或将同一选定引擎暴露为本机服务：

```bash
python3 scripts/collect_market_evidence.py \
  --engine ego-browser --serve 127.0.0.1:8791
```

服务不保存请求、客户资料、Cookie 或登录凭证，且拒绝非 localhost 监听。Ego Lite
只能在装有它的 macOS 主机上执行；若 Hermes 未来移到 Linux/云端，应改用已配置的
Playwright 认证上下文或其他显式页面适配器，而不是模拟 Ego 已登录数据。

## 证据完成条件

- `candidates`：2km 全量空间候选；
- `benchmark_set`：基于确定规则选出的价格/视觉标杆；
- `room_types`、`images`、`pricing`：仅对标杆集核验。

`collection_result.status` 是五类覆盖度的总状态；`competitor_analysis.collection_status`
与 `spatial_collection.status` 只判断 2km 空间候选池；后者必须与 OTA 请求的
`candidate_pool` 精确相同。故 OTA 的 P1/售罄/登录门槛可令回执保持 `partial`，但不能抹掉
已完整的 2km 竞品集合或其已经取得的视觉证据；它只会令 ADR 保持不可用。

图片交付为内嵌 JPEG/PNG/WebP，附来源 URL、采集时间、MIME 与 SHA-256；报价附
OTA 房源/房型 ID、可订状态、税费、取消政策、来源 URL 和时间。只有这些字段与
统一 `pricing_context` 都完整时，Skill 才允许进入 ADR 样本；即使满足也仍需三家
独立的中/高置信度正式竞品。
