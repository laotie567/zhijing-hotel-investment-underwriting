# 无 Codex Computer Use 的端到端验收

本验收证明当前 Skill 可以部署在 Mac Mini/Hermes 等宿主上：页面数据、房型和图片
由明确的页面采集引擎取得，Skill 只消费 JSON 回执。它不调用 Codex Computer Use，
不依赖当前开发机的可视化界面，也不会保存 Cookie。

## 验收范围与样例

脱敏样例：`笨酒店`，地址为“成都市成华区望平街滨河路6号”，联营轻改 17 间。为使
财务输入完整，验收使用 8 间单机大床 + 9 间双机双床、合计 26 机位的**基准示例假设**；
它仅验证技术链路，不能代替真实合同、成本、房型或投资决策。

页面候选的实时数量可变。验收记录保留在宿主的受控运行目录，不提交到 Git；文档只
规定需要核对的回执关系，避免将某次页面数量误写为长期阈值：

| 阶段 | 选定引擎/Profile | 当次结果 | 结论 |
|---|---|---|---|
| 2km 候选 | Playwright / `360-map-v1` | 确认 GCJ-02 中心点、全量候选、`spatial_collection`（中心/数量/ID 指纹） | 可追溯的完整空间候选池 |
| OTA 标杆 | Ego Lite / `ctrip-hotel-v1` 或 Ui.Vision+OpenCLI / `ctrip-live-rates-v1` | 将**全量**候选作为 `candidate_inventory`，并原样传入 `candidate_pool`；仅最多 8 个已选标杆采集房型/图片/报价 | CLI 验证回传池、引擎/Profile与中心一致；图片可进入 HTML/Base 附件 |
| 同条件价格 | OTA Profile | 登录、验证码、售罄或页面未回显日期/人数 | 回执可为 `partial`；P1/P2 观察保留，`pricing_context_unverified` 或其他资格缺口不得形成 ADR |
| 投测和交付 | `run.py` | 基准输入的财务机械、HTML、Bitable manifest | 空间池完整时为 `ready_for_review`；缺价格/图片会保留待补项和空 ADR，不自动改写财务 |

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
   `candidate_inventory`，并把原回执 `spatial_collection` 原样填入 `candidate_pool`。
   仅将人工或已授权适配器确认过的地图实体标成 `benchmark_selected`（最多 8 家）；
   对 `ctrip-hotel-v1`，为每一个标杆添加稳定 `ota_property.property_id`、URL、匹配方式
   及时间；`ctrip-live-rates-v1` 只允许名称与地址城市均唯一精确的自动映射。以相应引擎运行。

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
- **通过空间市场结论**：全量候选完成，且 OTA 回执原样返回匹配的 `spatial_collection`；
  此时可审阅正式竞品集合。
- **通过 ADR 参考**：在空间结论基础上，标杆集的同条件价格满足严格 P2 资格，且同机位
  有至少三家独立中/高置信度正式竞品的同条件可订报价。
- **价格被登录、验证码、售罄或页面条件缺失阻断**：保留已取得的候选/图片，采集回执
  为 `partial`，ADR 保持不可用；若空间池完整，仍为 `ready_for_review` 并在交付物中列出
  缺口。管理员完成正常登录后重跑；不得将列表价、不同日期价或模型猜测写入 ADR。

## 交付物与留存

将脱敏的 JSON 回执、HTML 与 Bitable manifest 留在宿主的受控运行记录中，不要提交
到 Git。Git 只包含契约、Profile 源码、测试 fixture 与文档；不会保存客户地址、Cookie、
截图、OTA 完整页面或飞书凭证。
