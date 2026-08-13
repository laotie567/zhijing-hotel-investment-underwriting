# 单一 Skill 测试与发布验收

## 必测行为

- 未确认点位不生成竞品结论；
- `market-evidence-collection/v1` 必须拒绝大于 2km 的页面采集范围、未知引擎、无页面回执或“覆盖度不完整却声称 complete”的结果；Playwright 与 Ego Lite 都是显式 Profile，不得静默回退到其他引擎；
- `--preflight --all-engines` 必须把缺少 Ego Lite、Kimi WebBridge 适配器/扩展或其他运行时明确标为 `action_required` 并给出安装动作；
- 只保留 2km 内、与中心同一地图 provider、营业中、主营电竞住宿且来源完整的正式竞品；
- 重复 `provider_place_id`、缺少来源和不完整采集阻断正式结论；
- 同一酒店的多条房型报价只计一个独立样本；仅同一入住日期、晚数、人数、CNY、可订状态、税费和取消口径均完整的中/高置信度报价可计入，至少三家独立竞品才产生 ADR 参考；
- `run.py` 同时返回竞品分析和财务预评估，且不自动改写收入假设；
- 未知或非法 `project_input` 字段在公共入口失败；
- `calculate.py` 不能作为独立 CLI 绕过 2km 阶段；
- 静态回本月数必须复现历史“初投 ÷ 首年平均月经营净现金”口径，并同时返回保守向上取整月数；首年经营净现金非正时不得伪造回本月数；
- `--format html` 生成移动端可读的独立 HTML，包含竞品房型/报价表、独立视觉竞品对标区、已计算的月度回本表和已提供的内嵌图片；无图片时明确提示补证，不加载外部脚本、样式或图片，并保留 `pre_evaluation_only` 结论范围；
- `--format bitable` 生成八张标准表的无凭证交付清单；它必须保留已计算的核心财务结果、完整输入路径、竞品/报价/视觉证据和 `pre_evaluation_only` 范围，且不得含公式、查找字段、飞书凭证或远程图片抓取；
- 缺少房型、2km 竞品或正式竞品图片时，Bitable manifest 不得产生静默空表：三张专题表各有可见待补记录，项目总表和 `delivery_gate` 必须为“待补证据”；所有待补项关闭后，项目总表仍先为“待写入核验”，只有宿主读回记录、关联和附件后才可标记“可交付”；
- 财务 Golden Master 和核心回归保持通过。

## 命令

```bash
git add -A

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s hotel-investment-underwriting/tests -p 'test_*.py'

python3 /path/to/skill-creator/scripts/quick_validate.py hotel-investment-underwriting

node --check hotel-investment-underwriting/collector/playwright_360_map.mjs
node --check hotel-investment-underwriting/collector/ego_ctrip.mjs
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
- [ ] 用已授权的来源页面跑一次 Playwright 地图 Profile 和 Ego Lite OTA Profile；对全量 2km 候选、标杆集、房型、图片以及同条件房态/价格逐项人工抽检；保存不含 Cookie 的页面回执。每次更换/更新 Ego Lite、Kimi WebBridge、crawl4ai、xcrawl 或 OpenCLI Profile 后也执行此验收；
- [ ] 在目标 Mac Mini 上执行 `--preflight --all-engines`；确认要求使用的 Profile 均为 `ready`，并对未安装的浏览器/扩展保留可执行的 `install_hint`；
- [ ] 在不具备 Skill 目录的浏览器环境打开 HTML，验证文字、表格和内嵌图片可见；
- [ ] 用获授权的 Feishu 身份读回标准模板的八张表及字段；首次真实项目写入时，再核验记录键、关联、`交付完整性`/`交付状态` 和已提供的视觉附件。
- [ ] 生产 ZIP 只包含唯一 Skill 的运行文件和包内 `VERSION`；
- [ ] 不含密钥、历史客户资料、测试、样例、旧包或历史 ZIP；
- [ ] `VERSION`、`CHANGELOG.md` 和输出 `skill_version` 已同步更新；
- [ ] 以已验证 tag 打包，计算 ZIP 的 SHA-256，并在 GitHub Release 附件中记录该值。

## 端到端验收记录

开发环境应至少保留一条脱敏的真实页面验收记录，证明页面采集不是 Codex Computer
Use 的隐式行为。2026-08-13 已以“成都市望平街笨酒店、17 间联营轻改”跑通
Playwright 360 地图 → Ego Lite 携程 → `run.py` → 离线 HTML → Bitable manifest 的
完整链路：360 页面返回 88 家候选，Ego Lite 返回 2 张可嵌入图片及来源/哈希；未登录
价格如实为 `partial`，所以整体仍为 `pre_evaluation_only`。该运行使用基准财务假设，
不是项目投资结论，也不写入真实飞书 Base。

复现请求、验收断言、期望的 `partial` 条件与交付物边界见
[END_TO_END_ACCEPTANCE.md](END_TO_END_ACCEPTANCE.md)。页面数量会随数据源变动，
验收应检查回执、范围、图片来源、状态和不可伪造的缺口，不应把“88”硬编码为长期
业务阈值。
