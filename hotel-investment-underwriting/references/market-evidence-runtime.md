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
| `ego-browser` / `ctrip-hotel-v1` | 已登录 OTA 的房型、可订状态、同条件价格、页面图片 | 安装 **Ego Lite**（不是 Eagle），确认 `ego-browser` 命令可用；在 Ego Lite 登录获授权 OTA 后重跑。安装指南：<https://lite.ego.app/document/zh/docs/quick-start>。 |
| `kimi-webbridge` | 真实浏览器会话的替代页面适配器 | 安装并连接 Kimi WebBridge 浏览器扩展，设置 `MARKET_EVIDENCE_KIMI_WEBBRIDGE_COMMAND`。若预检提示缺失，按 <https://kimi.com/features/webbridge> 安装/连接。 |
| `crawl4ai` / `xcrawl` / `opencli` | 经批准的静态页、检索或补采适配器 | 安装批准实现，并设置相应 `MARKET_EVIDENCE_*_COMMAND`。 |

预检不安装软件、不读取 Cookie、不打开页面。Hermes 应在首次部署、升级浏览器/扩展
或 Profile 后主动运行一次，并把 `install_hint` 原样展示给管理员。

## 受控的两阶段采集

1. 用 `360-map-v1` 建立 **全量 2km 候选集**。它对每家候选保留同源地图实体、坐标
   和来源，同时按距离选择有限数量的 `benchmark_selected` 标杆，不要求所有泛候选
   都有图片或价格。
2. 将全量候选放进 `candidate_inventory`；仅为选中标杆写入经页面确认的 `ota_property`
   映射，再用 `ego-browser --engine ego-browser` 运行 `ctrip-hotel-v1`。

`ota_property` 必须包含 `platform`、稳定 `property_id`、详情页 URL、匹配方式和
带时区匹配时间。它是“地图实体 ↔ OTA 房源”的显式桥梁，不能凭名称猜测。`ctrip-hotel-v1`
会以 `property_id` 构造携程 PC 详情页的 `checkIn`/`checkOut`/`adult` URL，并从渲染
页面复核日期、晚数和成人数。映射可以
由已配置的 Kimi WebBridge/crawl4ai/xcrawl/OpenCLI 页面适配器建立，但必须回传同一
字段。

`ctrip-hotel-v1` 只会在页面同时显示房型、可订、价格、税费口径、取消政策和完全相同
的 `pricing_context` 时，把它写入 `room_offers`。未登录显示“登录看低价”、验证码、
售罄或页面字段缺失都会产生 `partial`；不会用列表价替代。

## Hermes 调用

Hermes 只需在 Skill 目录内调用：

```bash
python3 scripts/collect_market_evidence.py \
  --engine playwright --input /path/to/360-request.json --format skill-patch

python3 scripts/collect_market_evidence.py \
  --engine ego-browser --input /path/to/ctrip-request.json --format skill-patch
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

图片交付为内嵌 JPEG/PNG/WebP，附来源 URL、采集时间、MIME 与 SHA-256；报价附
OTA 房源/房型 ID、可订状态、税费、取消政策、来源 URL 和时间。只有这些字段与
统一 `pricing_context` 都完整时，Skill 才允许进入 ADR 样本；即使满足也仍需三家
独立的中/高置信度正式竞品。
