# 单一 Skill 测试与发布验收

## 必测行为

- 未确认点位不生成竞品结论；
- `market-evidence-collection/v2` 必须拒绝大于 2km 的页面采集范围、未知引擎、无页面回执、无效/跨主机 HMAC 证明或“覆盖度不完整却声称 complete”的结果；OTA 二阶段必须带完整 `candidate_pool`，并拒绝引擎/Profile/中心/候选数量、ID 指纹或不可变候选快照与请求不一致的回执；Playwright、Ego Lite 与携程实时价均是显式 Profile，不得静默回退到其他引擎；
- `--preflight --all-engines` 必须把缺少 Ego Lite、Ui.Vision/OpenCLI 配对、多个已连接的 OpenCLI Browser Bridge Profile（仅允许 `ctrip-price-worker` default）、OpenCLI Ctrip 搜索命令、Python 3.10+ / 锁定 Scrapling DOM 解析器、Kimi WebBridge 适配器/扩展或其他运行时明确标为 `action_required` 并给出安装动作；
- 只保留 2km 内、与中心同一地图 provider、营业中、主营电竞住宿且来源完整的正式竞品；名称仅含“电竞房”的普通酒店不得被误判为主营电竞住宿；
- 重复 `provider_place_id`、缺少来源和不完整采集阻断正式结论；
- 同一酒店的多条房型报价只计一个独立样本；仅同一入住日期、晚数、人数、CNY、可订状态、税费和取消口径均完整、且携程 P2 从真实捕获的原始房型卡 DOM 经版本化 Scrapling 解析并与 Network 双证据一致的中/高置信度报价可计入；总价/套餐金额不得被冒充为每晚价。页面未回显报价条件时必须标记 `pricing_context_unverified`，布局漂移时必须标记 `DOM_SCHEMA_DRIFT` / `dom_parser_unverified`，至少三家独立竞品才产生 ADR 参考；
- `run.py` 同时返回竞品分析和财务预评估，且不自动改写收入假设；
- 未知或非法 `project_input` 字段在公共入口失败；
- `calculate.py` 不能作为独立 CLI 绕过 2km 阶段；
- 静态回本月数必须复现历史“初投 ÷ 首年平均月经营净现金”口径，并同时返回保守向上取整月数；首年经营净现金非正时不得伪造回本月数；
- `--format html` 生成移动端可读的独立 HTML，包含带 URL/时间追溯的竞品页面房型观察（非报价）、竞品房型/报价表、独立视觉竞品对标区、已计算的月度回本表和已提供的内嵌图片；无图片时明确提示补证，不加载外部脚本、样式或图片，并保留 `pre_evaluation_only` 结论范围；
- `--format bitable` 生成八张标准表的无凭证交付清单；它必须保留已计算的核心财务结果、完整输入路径、竞品页面房型观察/报价/视觉证据、标杆排序依据和 `pre_evaluation_only` 范围，且不得含公式、查找字段、飞书凭证或远程图片抓取；
- 缺少房型、2km 竞品或正式竞品图片时，Bitable manifest 不得产生静默空表：三张专题表各有可见待补记录，项目总表和 `delivery_gate` 必须为“待补证据”；所有待补项关闭后，项目总表仍先为“待写入核验”，宿主读回记录、关联和附件后只能标记“写入已核验”，不能提升市场、ADR 或投决状态；
- 财务 Golden Master 和核心回归保持通过。

## 命令

```bash
# 仅暂存本次明确要发布的文件；不要把客户资料或临时结果一并加入索引。
git add <intended-files>

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s hotel-investment-underwriting/tests -p 'test_*.py'

python3 /path/to/skill-creator/scripts/quick_validate.py hotel-investment-underwriting

node --check hotel-investment-underwriting/collector/playwright_360_map.mjs
node --check hotel-investment-underwriting/collector/ego_ctrip.mjs
node --check hotel-investment-underwriting/collector/ctrip_live_rates.mjs
```

## 入口文档负载（维护者 QA）

若维护环境安装了 YAO Meta Skill，在发布前运行下列检查。它只评估维护质量，既不
属于生产发布包，也不是 Skill 的运行时依赖：

```bash
YAO_META_SKILL=/path/to/yao-meta-skill
python3.11 "$YAO_META_SKILL/scripts/resource_boundary_check.py" \
  hotel-investment-underwriting
```

当前 Production 门槛为估算初始加载不超过 1,000 tokens；完整 Schema、方法论和
示例应留在 `schemas/` 与 `references/`，不应复制回 `SKILL.md`。

## 发布门槛

- [ ] 所有 Skill 测试通过；
- [ ] Skill 结构校验通过；
- [ ] 维护者资源边界检查通过；该检查工具不进入生产 ZIP；
- [ ] 用脱敏完整请求分别验证 JSON、Feishu 摘要、HTML 和 Bitable manifest 输出；
- [ ] 用已授权的来源页面跑一次 Playwright 地图 Profile、Ego Lite OTA Profile 和（如作为生产报价源）Ui.Vision+OpenCLI 携程实时价 Profile；对全量 2km 候选、最多 8 家标杆、房型、图片以及同条件房态/价格逐项人工抽检；确认每条 P2 通过 Network/DOM 和 `ctrip-dom-parser/v1`，保存不含 Cookie 的页面回执。每次更换/更新 Ego Lite、Ui.Vision、OpenCLI、Scrapling 注册表、Kimi WebBridge、crawl4ai 或 xcrawl Profile 后也执行此验收；
- [ ] 在目标 Mac Mini 上执行 `--preflight --engine ego-browser`，并检查 Playwright 地图运行时；确认标准 Profile 为 `ready`，并对显式启用的可选引擎保留可执行的 `install_hint`；
- [ ] 将 `HERMES_AGENT_AGENTS_TEMPLATE.md` 中的代码块部署为 Hermes 子 Agent 的 `AGENTS.md`；用一个脱敏地址验证该 Agent 会先执行预检、调用地图与 OTA CLI、拒绝手工 `market_evidence`，并在证据不完整时如实返回 `pre_evaluation_only`；
- [ ] 在不具备 Skill 目录的浏览器环境打开 HTML，验证文字、表格和内嵌图片可见；
- [ ] 用获授权的 Feishu 身份读回标准模板的八张表及字段；首次真实项目写入时，再核验记录键、关联、`交付载荷状态`/`市场证据状态`/`ADR证据状态`/`投决准备状态`、各子表 `交付状态` 和已提供的视觉附件。
- [ ] 生产 ZIP 只包含唯一 Skill 的运行文件和包内 `VERSION`；
- [ ] 不含密钥、历史客户资料、测试、样例、旧包或历史 ZIP；
- [ ] `VERSION`、`CHANGELOG.md` 和输出 `skill_version` 已同步更新；
- [ ] 以已验证 tag 打包，计算 ZIP 的 SHA-256，并在 GitHub Release 附件中记录该值。

## 端到端验收记录

开发环境应至少保留一条脱敏的真实页面验收记录，证明页面采集不是 Codex Computer
Use 的隐式行为。验收必须覆盖地图完整池 → 原样 `candidate_pool` → OTA 页证据 →
`run.py` → 离线 HTML → Bitable manifest，并记录实际候选数、标杆数、图片数和价格状态。
页面数量会变化，不能把单次运行数量当作业务常量；未登录或价格条件不一致必须如实为
`partial`/不可 ADR，而不能让页面采集缺口倒灌为伪造数据或覆盖既有空间结论。该记录
使用基准财务假设，不是项目投资结论，也不写入真实飞书 Base。

复现请求、验收断言、期望的 `partial` 条件与交付物边界见
[END_TO_END_ACCEPTANCE.md](END_TO_END_ACCEPTANCE.md)。页面数量会随数据源变动，
验收应检查回执、范围、图片来源、状态和不可伪造的缺口，不应把单次候选数量硬编码为长期
业务阈值。
