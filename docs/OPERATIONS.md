# 单一 Skill 运行说明

## 日常流程

1. 收集地址、计划改造房量、合同/成本/收入假设。
2. Hermes 子 Agent 必须按 [HERMES_AGENT_AGENTS_TEMPLATE.md](HERMES_AGENT_AGENTS_TEMPLATE.md) 的 `AGENTS.md` 约束执行；由宿主调用 `scripts/collect_market_evidence.py`，先确认服务环境已安全设置至少 32 字节的 `MARKET_EVIDENCE_RECEIPT_HMAC_KEY`，存在歧义时让用户选择同源地图点位后重试。
3. 分开读取两类状态：`spatial_collection`/`competitor_analysis.collection_status` 证明全量 2km 候选是否完成；五项覆盖度和 `collection_result.status` 说明标杆房型、图片及价格是否齐全。OTA 任一维度未完成会使回执为 `partial` 并阻止 ADR，但不会抹掉已完成的空间竞品结论。
4. 将其 `skill-patch` 合并进项目财务输入，执行 `scripts/run.py`。
5. 先看竞品状态，再看财务结论；需要时补充数据并重新运行。
6. 需要交付竞品调研时，以同一请求执行 `--format html > competitor-research.html`；将该单文件交给业务方，无需一并交付 Skill 目录。
7. 需要飞书多维表格交付时，以同一请求执行 `--format bitable > bitable-delivery.json`；由获得该 Base 写权限的宿主校验八张标准表后，按清单中的记录键写入、解析关联、再上传内嵌图片。读回只能更新“交付载荷状态”；市场、ADR 和投决范围必须分别读取，不能被写入成功掩盖。

## 结果处理

| 结果 | 含义 | 下一步 |
|---|---|---|
| `ready_for_review` | 全量 2km 候选集完整，已完成正式竞品筛选 | 审核当前可用证据；若价格/图片为 partial，先补证，ADR 仍不可用。明确选择财务收入假设。 |
| `pre_evaluation_only` | 点位或全量 2km 空间候选证据不完整 | 补齐空间证据，不将结果称为完整竞品结论。 |
| `needs_location_confirmation` | 中心点未确认 | 回到宿主完成地图候选选择。 |
| `evidence_insufficient` | 候选集部分采集、来源缺失或重复地图 ID | 保留现有候选与排除原因，补证而不扩大半径。 |

## 常见问题

- 无法确认地址：不要让模型猜坐标；请求更精确地址或用户选择地图候选。
- 页面采集器不可用或 Profile 返回的页面结构变更：不要静默换源或回填旧数据；记录引擎/Profile/页面回执，只有真实 HTTP 响应才记录状态码，无法观察时明确写 unknown，修复或切换为另一个明确配置的页面引擎后重跑。
- OTA 二阶段请求被拒绝：确认传入的是地图回执原样的完整 `candidate_pool`；引擎、Profile、中心点、候选数量和 provider-place-ID 哈希都必须与回执相符，不能手工删改或只传 8 家标杆。
- 携程自动映射失败：`ctrip-live-rates-v1` 只在酒店名唯一精确且地址含可核验城市、搜索结果城市也一致时自动映射；补齐 `target.address` 或改为人工确认 `ota_property`，不要按名称猜测。
- 实时报价预检失败：完成 Ui.Vision 配对、OpenCLI Browser Bridge 连接，并确保 `opencli ctrip search --help` 可用。旧的中断锁会在记录进程已不存在时自动回收；只有没有有效 PID 的异常锁才按 12 分钟过期回收。仍显示 busy 时等待当前任务结束，不要手工抢占活跃浏览器。
- 新 Mac Mini/Hermes：标准链路先执行 `collect_market_evidence.py --preflight --engine ego-browser`，地图池按 Playwright 要求验收；若 Ego Lite 不在 `ready`，将 `install_hint` 展示给管理员并停止相应采集，不得伪造登录态或降级为无口径报价。携程实时价 Worker、Kimi WebBridge 等只在宿主显式启用时才需预检。
- Hermes 子 Agent 未按顺序调用地图、OTA 与 `run.py`：停止该运行，不采纳其手工拼装的竞品、图片或投资结论；检查其工作目录是否已加载严格 `AGENTS.md`，再从预检重新开始。
- 需要验证“不依赖 Codex Computer Use”的部署：以同一请求分别运行 `--engine playwright` 与 `--engine ego-browser`，检查两个页面回执和 `collector.engine`；不要使用桌面操作录屏或模型摘录替代 CLI 输出。完整步骤见 `END_TO_END_ACCEPTANCE.md`。
- 2km 内没有合格竞品：如采集标记为 `complete`，这是有效结论；不要扩大半径来凑样本。
- 有竞品但同机位少于三家独立物业：展示竞品，不输出对应机位 ADR 建议。
- 有三个低置信度报价但没有三个中/高置信度报价：展示全部竞品和低置信度排除数，不输出对应机位 ADR 建议。
- 报价不是同一入住日期、晚数、人数、币种或可订状态：不要混合报价；补齐一次统一的 `pricing_context` 后以页面 Profile 重跑。
- 候选地图 `provider` 与中心点不同：不要混合地图实体 ID；从中心点的同一 provider 重新取候选。
- 报价已过宿主规定的采集有效期：重新采集并更新 `observed_at`，不要复用旧价格形成建议 ADR。
- 竞品 ADR 与财务输入不同：这是预期行为；由审核人显式选择模型输入后重跑。
- 回本周期：先看“静态回本”（历史表的初投 ÷ 首年平均月经营净现金）和其向上取整月数，再结合“动态回本（折现）”。静态月数不包含后续设备重置；动态月数保留完整年度现金流的重置、残值和折现约束。
- 财务计算失败：修正 `project_input`，不要使用语言模型手算替代。
- HTML 图片未显示：只提供 JPEG/PNG/WebP 的 `data_uri`，不要在 `data_uri` 中填远程 URL；图片必须绑定本次正式竞品的 `provider_place_id`。
- 飞书表格未出现图片：先确认视觉证据记录已按 `证据记录ID` 建立，再只上传清单内的 `data_uri`；`source_url` 是来源追溯链接，不能被当作图片下载地址。
- 飞书表格出现旧数值：用 `项目运行ID` 和各表的记录键匹配写入；同一 `input_sha256` 可更新同一运行，变更请求必须保留为新的运行，而非覆盖历史结论。

宿主可保存请求和结果用于审计，但运行 Skill 本身不创建状态、锁或归档目录。
