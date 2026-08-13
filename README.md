# 智竞未来电竞酒店投测 Skill

当前发布版本：`0.9.0`。这是一个用于签约前判断的单一生产 Skill，不是独立 App、审批系统、爬虫平台或项目数据库。

它只做两件事：

1. 分析确认点位 2km 内的纯电竞酒店竞品，输出可追溯竞品集和 ADR 参考；
2. 用确定性财务机械计算投资、收入、成本、NPV、IRR、按月静态/动态回本期、盈亏平衡 OCC、退出红线和谈判底线。

在上述结果完成后，Skill 可额外输出一份独立、响应式、单文件 HTML 竞品调研报告，含正式竞品的视觉对标区和已计算的投资回报/按月回本表；它只是结果交付层，不参与任何 2km、ADR 或财务判断。

## 唯一生产发布物

只发布 `hotel-investment-underwriting/`。宿主负责对话、地址确认、已授权地图或证据采集、密钥、持久化和消息发送；Skill 不拥有这些系统。

```mermaid
flowchart LR
    H["宿主 Agent / 飞书"] --> R["单一 Skill 请求"]
    E["已授权地图与竞品证据"] --> R
    R --> S["hotel-investment-underwriting"]
    S --> O["2km 竞品结论 + 投资预评估 + 可选 HTML 调研报告"]
```

## 核心规则

- 只接受确认的 GCJ-02 中心点和同坐标系候选点；Skill 自行计算 0–2,000 米 Haversine 距离。
- 正式竞品必须是营业中的主营电竞住宿，候选与中心点使用同一地图 `provider`，并有完整来源记录。
- 仅在采集完整、同一 `pricing_context`（入住日期、晚数、人数、CNY）下，同机位至少有三家独立的中/高置信度正式竞品时，才输出按 10 元取整的中位数 ADR 参考；低置信度来源仍展示，但不计入 ADR 样本。
- 竞品建议不会自动写入财务输入；由分析人员显式选择收入假设。
- 竞品证据不完整时，Skill 输出和嵌套财务结果的 `conclusion_scope` 固定为 `pre_evaluation_only`，不构成完整的竞品结论。
- 财务结果同时给出历史投资表口径的 `static_payback_months`（一次性初投 ÷ 首年平均月经营净现金）和折现持续回本的 `discounted_payback_months`；两者均附向上取整的整月值，不能互相替代。
- `scripts/run.py` 是唯一命令行入口；`calculate.py` 仅供 Skill 内部调用。

## 快速运行

```bash
python3 hotel-investment-underwriting/scripts/run.py \
  --input /path/to/skill-request.json \
  --defaults hotel-investment-underwriting/references/benchmark-defaults.json \
  --format feishu
```

生成可离线查看的竞品调研报告：

```bash
python3 hotel-investment-underwriting/scripts/run.py \
  --input /path/to/skill-request.json \
  --defaults hotel-investment-underwriting/references/benchmark-defaults.json \
  --format html > /path/to/competitor-research.html
```

HTML 内嵌样式、表格、文本以及请求中提供的 JPEG/PNG/WebP `data_uri` 图片；正式竞品的房图、装修观察、机位和同条件报价会集中在“视觉竞品对标”区，供人工调价研判。文件可脱离 Skill 运行环境在手机或电脑浏览器中打开；来源链接仅用于在线追溯，视觉证据不会自动改写 ADR 或财务输入。

请求契约见 [skill-request.schema.json](hotel-investment-underwriting/schemas/skill-request.schema.json)，财务字段见 [input-schema.md](hotel-investment-underwriting/references/input-schema.md)。

## 文档入口

- [架构边界](docs/ARCHITECTURE.md)：宿主、Skill 与人工职责，以及失败策略。
- [数据契约](docs/DATA_CONTRACTS.md)：请求、竞品事实、视觉证据与输出字段。
- [部署与打包](docs/DEPLOYMENT.md)：生产运行、单文件 HTML 与发布包清单。
- [运行说明](docs/OPERATIONS.md)：结果状态与补证动作。
- [测试与发布验收](docs/TESTING.md)：必测行为和上线门槛。
- [安全边界](docs/SECURITY.md)：凭证、来源和图片证据的处理规则。
- [Git 与版本](docs/GIT_WORKFLOW.md)、[版本说明](docs/VERSIONING.md)：提交、tag 与 GitHub 发布流程。

仓库只保留运行、验证和维护这一生产 Skill 所需的文本源码。过期的区位包、施工守卫、任务/授权状态、审批/回放控制面、爬虫实现及历史客户原始文件均不在当前发布分支；需要追溯时使用 Git 历史。
