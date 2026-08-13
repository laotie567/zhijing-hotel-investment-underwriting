# 无 Codex Computer Use 的端到端验收

本验收证明当前 Skill 可以部署在 Mac Mini/Hermes 等宿主上：页面数据、房型和图片
由明确的页面采集引擎取得，Skill 只消费 JSON 回执。它不调用 Codex Computer Use，
不依赖当前开发机的可视化界面，也不会保存 Cookie。

## 验收范围与样例

脱敏样例：`笨酒店`，地址为“成都市成华区望平街滨河路6号”，联营轻改 17 间。为使
财务输入完整，验收使用 8 间单机大床 + 9 间双机双床、合计 26 机位的**基准示例假设**；
它仅验证技术链路，不能代替真实合同、成本、房型或投资决策。

2026-08-13 的一次真实页面验收结果如下。地图候选的实时数量可变，因此这里只记录
当次回执，不将其作为永久测试常量：

| 阶段 | 选定引擎/Profile | 当次结果 | 结论 |
|---|---|---|---|
| 2km 候选 | Playwright / `360-map-v1` | 确认 GCJ-02 中心点，88 家候选，公开房型/图片覆盖完整 | 可追溯的全量候选池 |
| OTA 标杆 | Ego Lite / `ctrip-hotel-v1` | 将 88 家候选作为 `candidate_inventory` 传入；1 家已有显式携程房源 ID 映射的标杆取得 2 张图片、URL、时间与 SHA-256 | 图片可进入 HTML/Base 附件 |
| 同条件价格 | Ego Lite / `ctrip-hotel-v1` | OTA 页面显示“登录看低价” | `pricing=partial`，不得形成 ADR |
| 投测和交付 | `run.py` | 17 间、26 机位；智竞静态回本 17.9 月/向上取整 18 月，动态回本向上取整 19 月 | 仅 `pre_evaluation_only` |

## 在 Mac Mini 上复现

1. 从授权仓库检出已验证 tag，并执行部署预检：

   ```bash
   cd hotel-investment-underwriting/collector
   npm ci
   npx playwright install chromium
   cd ..
   python3 scripts/collect_market_evidence.py --preflight --all-engines
   ```

2. 以 `--engine playwright` 提交 `360-map-v1` 请求。保存 `--format result` 的 JSON，
   并检查 `target_resolution`、`collector.page_sources`、`coverage.candidates` 与每一条
   候选的同源 GCJ-02 坐标/来源。

3. 从该 JSON 传递完整 `competitor_analysis.candidates` 作为 OTA 请求的
   `candidate_inventory`。仅将人工或已授权适配器确认过的地图实体标成
   `benchmark_selected`，并为每一个标杆添加稳定 `ota_property.property_id`、URL、
   匹配方式及时间。以 `--engine ego-browser` 执行 `ctrip-hotel-v1`。

4. 将 OTA 采集结果作为 `market_evidence` 与项目财务输入组装，并分别运行：

   ```bash
   python3 scripts/run.py --input skill-request.json \
     --defaults references/benchmark-defaults.json --format json
   python3 scripts/run.py --input skill-request.json \
     --defaults references/benchmark-defaults.json --format html > competitor-research.html
   python3 scripts/run.py --input skill-request.json \
     --defaults references/benchmark-defaults.json --format bitable > bitable-delivery.json
   ```

5. 检查 HTML 仅含内嵌样式与 `data:image/` 图片；检查 manifest 的附件只来自这些
   `data_uri`，并在写入真实 Base 前读取 `delivery_gate`。本验收不调用飞书写入 API，
   真实项目写入另行使用已授权宿主并做读回验证。

## 通过与待补的判定

- **通过页面技术链路**：每段 JSON 都有匹配的 `collector.engine`、Profile、真实页面
  URL/HTTP 状态和带时区时间；所有图片都有 URL、MIME、SHA-256；HTML 可在无 Skill
  目录的设备上打开。
- **通过完整市场结论**：全量候选和标杆集的房型、图片、价格均为 `complete`，且同机位
  有至少三家独立中/高置信度正式竞品的同条件可订报价。
- **价格被登录、验证码、售罄或页面条件缺失阻断**：保留已取得的候选/图片，输出
  `partial` 和 `pre_evaluation_only`。管理员在 Ego Lite 完成正常登录后重跑；不得将
  列表价、不同日期价或模型猜测写入 ADR。

## 交付物与留存

将脱敏的 JSON 回执、HTML 与 Bitable manifest 留在宿主的受控运行记录中，不要提交
到 Git。Git 只包含契约、Profile 源码、测试 fixture 与文档；不会保存客户地址、Cookie、
截图、OTA 完整页面或飞书凭证。
