# 版本与发布

当前开发版本为 `0.10.0`。生产发布物只有
`hotel-investment-underwriting/`，其包内 `VERSION` 是唯一版本来源：

| 项目 | 当前状态 |
|---|---|
| 单一 Skill 入口 | `hotel-investment-underwriting/0.10.0` |
| 财务计算器 | 3.1.0，保留并由 Golden Master 锁定 |
| 财务输入契约 | `project-input.schema.json` |
| 2km 竞品请求契约 | `skill-request.schema.json` |
| 竞品调研交付 | `--format html` 的独立单文件 HTML，含视觉竞品对标区 |
| 飞书多维表格交付 | `--format bitable` 的标准八表无凭证 manifest；宿主应用它，不重复计算 |

采用 `MAJOR.MINOR.PATCH`：不兼容的请求/输出契约变更升 MAJOR，向后兼容的新
能力升 MINOR，修复升 PATCH；不改变契约、脚本逻辑或计算口径的入口文案/上下文
压缩也升 PATCH。每次发布同时更新包内 `VERSION`、`CHANGELOG.md`
和 `scripts/run.py` 输出的 `skill_version`，运行核心测试与 Skill 结构校验，并从
已验证 tag 打包唯一的 Skill 目录。宿主的地图/证据能力、凭证、持久化和消息通道
不随本 Skill 发布。
