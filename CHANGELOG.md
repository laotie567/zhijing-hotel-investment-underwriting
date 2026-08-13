# 变更记录

## 1.0.0 - 2026-08-14

### Breaking changes / migration

- 页面市场证据契约升级为 `market-evidence-collection/v2`。旧 `v1` 页面回执和 OTA 请求不会被新运行器接受：先以新的地图 Profile 重跑 2km 候选池，再把其完整 `candidate_inventory` 与原样 `spatial_collection` 作为 OTA 的 `candidate_pool` 重新采集。
- `run.py` 不再接受脱离页面采集回执的 `competitor_analysis` 或 `competitor_report`。宿主必须把 `--format skill-patch` 的完整 `market_evidence` 一并传入；只做纯财务预评估时可不带市场证据。

### Fixed

- 强制将页面采集回执绑定到唯一 `market_evidence`：没有回执的竞品分析、HTML 视觉证据或飞书竞品交付全部在唯一入口失败；只有纯财务预评估可无市场回执运行。
- 新增地图→OTA 的不可变空间交接：OTA 请求必须携带完整 `candidate_pool`，含确认中心、地图引擎/Profile、候选数和排序地点 ID 的 SHA-256；结果必须原样回传为 `spatial_collection`。CLI 额外拒绝引擎、Profile、中心或候选池错配。
- 统一两条状态轴：全量 2km 空间池完成后可保留 `ready_for_review`，即使 OTA 房型/图片/价格回执为 `partial`；后者仍严格阻断 ADR，并在 HTML/Base 交付中保留待补项。
- 携程 P2 页面未回显请求日期和人数时固定写入 `pricing_context_unverified`，永不 ADR-eligible；自动携程映射改为名称唯一精确且地址/搜索城市一致才可进行。
- 携程公开图片仅接受酒店、房型或图库上下文，排除头像、Logo、二维码；所有标杆共用 7.5MB 嵌入图片预算。
- 携程实时价临时锁增加死进程恢复；只有无有效 PID 的异常锁按 12 分钟过期，避免异常中断后永久阻塞且不抢占活跃浏览器。

### Added

- 2km 竞品调研保留固定深调标杆的 `benchmark_rank` 与 `benchmark_selection_reason`；HTML 与飞书 `2km竞品` 表可追溯最多 8 家标杆为什么被优先采集。
- 携程实时价预检新增无副作用的 `opencli ctrip search --help` 检查，缺少自动映射插件会给出明确安装动作。

### Validation

- 新增无回执竞品注入拒绝、完整空间池证明、OTA 回执绑定、P2 上下文资格、地址城市解析、死锁恢复、标杆理由和飞书标杆字段回归；文档、请求 schema、部署步骤和端到端验收同步为同一状态模型。

## 0.13.0 - 2026-08-13

### Added

- 新增内置 `ctrip-live-rates` / `ctrip-live-rates-v1`：以专用 Chrome `ctrip-price-worker` Profile 采集已登录携程的页面价格、房型、可订状态和公开图片。Ui.Vision 是唯一页面动作执行者，OpenCLI 只读 Network/DOM；不依赖 Codex Computer Use。
- 新增唯一精确的携程实体映射：缺少 `ota_property` 时，仅接受 `opencli ctrip search` 的单一精确名称结果，生成可追溯 OTA ID/URL；零个或多个结果返回 `HOTEL_MAPPING_AMBIGUOUS`。
- 新增结构化 `collection_issues`，覆盖 Ui.Vision 未配对、登录/验证码、无库存、查询条件不一致、Network/DOM 价格不一致及页面动作失败；不会再以空报价掩盖失败。
- HTML 与飞书“竞品报价与视觉证据”新增页面价格观察、P1/P2/P3 级别、Network/DOM 验证、价格一致性、ADR 资格及排除原因。

### Guardrails

- 页面价格先作为 `pricing_observations` 交付。只有完全相同的入住条件、Network/DOM 一致、可订、税费、取消政策和机位数全部成立时，才写入严格 `room_offers`，并仍须满足三家独立竞品规则后才形成 ADR。
- 实时价 Worker 使用临时单任务锁；回执和诊断不输出 Cookie、请求头、令牌或原始 Network body。`NO_INVENTORY` 作为已验证负向结果保留，绝不伪造价格。

### Validation

- 新增实时价 Profile、自动映射、双证据一致性、价格冲突拒绝、结构化问题、HTML/飞书页面价格观察和发布归档白名单的回归测试；全套 95 项测试、Skill 结构校验及发布归档检查通过。

## 0.12.0 - 2026-08-13

### Added

- 新增 `ego-browser` / `ctrip-hotel-v1` 正式 OTA 页面采集 Profile：使用 Ego Lite 的隔离、已登录浏览器 Space 采集已选价格/视觉标杆的房型、可订状态、同条件报价和公开图片；图片回执附采集时间、MIME 与 SHA-256，可直接进入独立 HTML 与飞书附件交付。
- 新增 `market_evidence_runtime.py` 与 `collect_market_evidence.py --preflight --all-engines`。Hermes 或新 Mac Mini 可在不打开页面、不读取 Cookie 的前提下检查 Playwright、Ego Lite、Kimi WebBridge 及外部适配器；缺少 Kimi 扩展/守护进程/JSON 适配器会输出明确的安装配置动作。
- 页面市场证据契约新增全量 `candidates` 与有限 `benchmark_set` 两层：地图 Profile 覆盖完整 2km 候选，报价与视觉 Profile 只覆盖显式选定、已绑定 OTA 稳定房源 ID 的标杆，避免把泛候选的缺图误判为完整采集失败。
- 飞书竞品与证据表新增 OTA 平台/酒店 ID/房型 ID、可订状态、税费口径、取消政策以及图片 MIME/SHA-256 字段，交付可回溯到同一次页面观察。

### Guardrails

- Ctrip Profile 以 `property_id` 构造包含 `checkIn`、`checkOut`、成人数的报价页，并从渲染内容复核统一报价条件。页面未登录、验证码、售罄、日期/人数不一致或税费/取消政策缺失时保持 `partial`，不把任何价格计入 ADR。
- ADR 样本现在逐条校验房型来源 ID、可订状态、币种、含税标记、取消政策、同一 `pricing_context`、来源 URL 和采集时间；不完整报价仅作为不可聚合的观察。
- Ego Lite 仅为装有它的 macOS 主机提供认证浏览器运行时。Linux/云端 Hermes 必须使用明确配置的 Playwright 或其他采集器，不能伪装成已登录 Ego 会话。

### Validation

- 新增 OTA 身份桥接、严格报价资格、Mac Mini/Kimi/Ego 预检与不存在隐式回退的回归；实测受控 Ctrip 页面可取得房型和嵌入式视觉证据，而未登录报价正确返回 `partial`。
- 完成“成都市望平街笨酒店、17 间联营轻改”脱敏端到端验收：Playwright 360 地图取得确认中心点与完整 2km 候选池；Ego Lite 携程 Profile 消费同一候选池并取得真实页面图片、来源回执与哈希；`run.py`、离线 HTML 与飞书 manifest 均保留 `pre_evaluation_only` 和可见待补项。完整复现与验收边界见 `docs/END_TO_END_ACCEPTANCE.md`。

## 0.11.0 - 2026-08-13

### Added

- 新增正式页面市场证据契约 `market-evidence-collection/v1` 与无界面 CLI/本机 HTTP 工具 `collect_market_evidence.py`。所有 Agent 平台均可先采集、取得 `skill-patch`，再调用唯一的确定性测算入口。
- 新增默认 `360-map-v1` Playwright Profile 和锁定的 Node 运行时：采集同源点位、2km候选、公开房型名称、公开房图、页面 URL/HTTP 回执和四项覆盖度。Kimi WebBridge、crawl4ai、xcrawl、OpenCLI 通过同一 JSON-stdin/stdout 业务契约成为可替换的正式页面采集引擎。

### Guardrails

- 页面采集不再是模型或 Codex Computer Use 的隐式能力。引擎、Profile、版本、采集时间和页面来源回执必须可追溯；未配置引擎不能静默回退。
- 地图列表价不会伪装成同条件房态价格。当前 360 Profile 对 `pricing` 明确返回 `not_collected`，使下游保持 `partial/pre_evaluation_only`，直至有能够按统一入住条件抓取可订状态与房价的页面 Profile。

### Validation

- 新增页面契约、2km上限、完整性、防回退和 Playwright 调用边界的离线回归；发布归档白名单纳入采集工具、Profile、锁定依赖和契约说明。

## 0.10.1 - 2026-08-13

### Fixed

- 修复飞书多维表格在房型、2km竞品或竞品图片证据缺失时出现静默空表的问题。Manifest `1.1` 会在相应子表写入明确的待补记录，不伪造房型、竞品、报价或图片事实。
- 项目测算总表新增 `交付完整性`、`交付待补项`；三张专题表新增 `交付状态`。顶层 `delivery_gate` 仅在房型、2km竞品和正式竞品视觉图片均已满足时标记 `final_delivery_eligible: true`；即使满足，宿主也须在附件读回前保持“待写入核验”。

### Guardrails

- 已授权宿主只可在 `delivery_gate.final_delivery_eligible` 为真时将运行标记为完整客户交付；其他结果可保留为带可见缺口的草稿，不能包装为完成。

### Validation

- 新增回归：缺房型、缺2km竞品、缺视觉图片分别生成可见待补行；完整交付必须通过专项门槛。

## 0.10.0 - 2026-08-13

### Added

- 新增 `--format bitable`：以当前同一轮 2km 竞品分析和确定性财务结果，生成可由已授权宿主写入的标准飞书多维表格交付清单。
- 新建八张标准表的生产模板：项目测算总表、输入参数与来源、投资与成本明细、年度收入与现金流、情景与敏感性、房型配置、2km竞品、竞品报价与视觉证据。
- 保留历史市场调研表常用的竞品展示字段（等级、开业/装修、房量、图片质量、设施、特色、评分、评论和周边），以可选 `market_profile` 接收，并严格限定为展示元数据。

### Guardrails

- 飞书仅接收已计算值、溯源字段、逻辑关联和已提供的图片字节；不含公式、查找字段、凭证、远程图片抓取、爬虫、数据库或审批/状态逻辑。
- 同一 `input_sha256` 的表格写入以逻辑记录键幂等更新；输入变化生成新的项目运行。视觉附件只能上传 manifest 中的 `data_uri`，来源 URL 仅供追溯。
- Bitable 输出完整保留 `pre_evaluation_only`，不能把证据不足的 2km 调研包装为完整结论。

### Validation

- 新增 Bitable manifest 的模板、核心财务不重算、输入/年度明细、竞品市场字段、视觉证据、预评估范围和公共 CLI 回归覆盖；发布归档白名单包含新的运行模块与交付说明。

## 0.9.0 - 2026-08-13

### Added

- 将历史“市场调研及投资回报表”的 `回款周期/月` 口径带回生产 Skill：每个投资方均输出 `static_payback_months`（一次性初投 ÷ 首年平均月经营净现金）及保守向上取整的整月值。
- 现有折现持续回收期新增月度交付字段 `discounted_payback_months` 及其向上取整值；场景输出同步提供智竞的静态/动态回本月数。

### Changed

- Feishu 摘要对智竞和业主完整成本视角都直接交付“静态回本 N 个月”和“动态回本 N 个月（折现）”，保留原始小数月数用于审计。
- 静态月数明确排除后续设备重置和末期残值；动态月数继续沿用年度完整现金流、重置、残值和折现规则，按 `1 年 = 12 个月` 表达，不伪造缺失的月度预测。

### Validation

- 新增历史月度回本公式、整月向上取整、首年经营净现金非正不伪造回本期以及 Feishu 展示的回归覆盖。

## 0.8.1 - 2026-08-12

### Changed

- 将生产入口 `hotel-investment-underwriting/SKILL.md` 压缩为请求、固定流程、硬规则和按需阅读索引；完整字段、媒体约束和计算解释继续留在既有 Schema 与 `references/` 中按需读取。
- 不改变触发描述、请求/输出契约、2km 竞品规则、财务机械、视觉 HTML 交付或发布包边界。这是一次行为不变的上下文效率修复。

### Validation

- 维护者资源边界检查通过：Production 初始加载估算为 963 tokens（门槛 1,000）。
- 60 项 Skill 回归、归档白名单测试和公共 CLI 冒烟测试通过。

## 0.8.0 - 2026-08-12

### Release

- 将生产发布版本与运行时 `skill_version` 收敛为包内 `hotel-investment-underwriting/VERSION` 的单一来源；发布包可独立追溯，不再依赖根目录版本文件。
- 补齐部署、运行、测试、版本与 GitHub 发布文档，明确从已验证 tag 打包、暂存树归档检查、HTML 离线验收和 SHA-256 记录。
- 发布归档改为精确白名单，并读取同一暂存/发布树的属性；未来误加入的客户 Office 文件、测试或其他运行时外文件会使发布测试失败。

### Removed

- 从当前发布分支移除 18 个历史客户 Excel/Word 原始文件及 Git LFS 规则。它们不被核心代码、Schema、测试或发布包使用；如需追溯，使用此前 Git 提交或受控业务档案。
- 删除旧运行时标识 `hotel-investment-underwriting-single-skill/1.2.0`，避免双版本来源和过期命名。

## 0.7.1 - 2026-08-12

### Added

- HTML 竞品调研报告新增独立“视觉竞品对标”区，集中展示正式 2km 竞品的已授权房图、装修观察、机位与同条件报价，供人工识别产品状态和调价研判。

### Guardrails

- 视觉区只复用既有 `competitor_report.candidate_media` 证据；仍只接受绑定到正式竞品的内嵌 JPEG/PNG/WebP 与来源链接，不引入远程图片、爬虫、状态服务或新的财务输入。
- 图片、装修观察和人工视觉研判不自动变更 ADR、竞品分类或财务结果；无视觉证据时报告明确提示补证。

### Validation

- 新增视觉区、无图片补证提示、图片仅嵌入一次和核心结果不受展示证据影响的回归覆盖；修复长文本在窄屏报告中的横向溢出。

## 0.7.0 - 2026-08-12

### Added

- 新增 `--format html`：以同一份 Skill 请求生成响应式、无 JavaScript 的独立竞品调研 HTML，含 2km 边界、竞品房型/报价、ADR 表、排除候选、结论范围和投资测算衔接。
- 新增可选 `competitor_report` 展示证据：按既有候选的 `provider_place_id` 绑定装修观察与来源信息；JPEG/PNG/WebP 图片以内嵌 `data_uri` 写入交付文件，可脱离 Skill 运行环境在手机或电脑浏览器打开。

### Guardrails

- 报告展示证据不参与 2km 分类、ADR 聚合或财务输入；错绑候选、远程图片地址、SVG 或不匹配的图片字节仅阻断 HTML 交付，不阻断 JSON/Feishu 的核心投测。
- `pre_evaluation_only` 会原样呈现在 HTML 中，不能被报告外观掩盖为完整竞品结论。

### Validation

- 新增单文件 HTML、移动端 viewport、内嵌图片、转义及预评估范围的入口回归测试，并将渲染模块纳入发布归档检查。

## 0.6.2 - 2026-08-12

### Changed

- 候选必须声明与确认中心一致的地图 `provider`，避免混用不同供应商的实体 ID。
- 新增每批报价共用的 `pricing_context`（入住日期、晚数、人数、CNY）；缺失或无效时不生成建议 ADR。
- 低置信度来源的正式竞品继续展示，但其报价不计入 ADR；每机位须有至少三家独立的中/高置信度物业才生成建议值。

### Validation

- 新增异地图 provider、缺少统一报价条件、低置信度报价和用户可见工作流说明的回归测试。

## 0.6.1 - 2026-08-12

### Changed

- 删除旧区位 Skill、房型规划包、施工守卫、任务/授权状态、审批/回放控制面、历史回测和爬虫实现，以及所有绑定文档与测试；客户原始资料继续只读保留。
- 将 `scripts/run.py` 固定为唯一命令行入口；`calculate.py` 改为内部财务模块，不能绕过 2km 竞品阶段。
- 在公共入口执行严格 `project_input` Schema 校验，拒绝未知字段和不合法数据。
- ADR 样本改为按独立 `provider_place_id` 计数；同物业多条报价先归并，重复 ID 或任一候选来源缺失均阻断正式竞品结论。
- 财务摘要在竞品未完成时明确标记为 `pre_evaluation_only`。

### Validation

- 保留并扩展财务 Golden Master、核心财务回归、2km 分类和唯一入口测试。
- 验证 Skill 归档仅包含运行文件，不包含客户资料、测试、旧包或仓库文档。

完整历史请使用 Git 提交记录追溯。
