# 版本与发布

当前开发版本为 `1.2.0`。生产发布物只有
`hotel-investment-underwriting/`，其包内 `VERSION` 是唯一版本来源：

| 项目 | 当前状态 |
|---|---|
| 单一 Skill 入口 | `hotel-investment-underwriting/1.2.0` |
| 财务计算器 | 3.1.0，保留并由 Golden Master 锁定 |
| 财务输入契约 | `project-input.schema.json` |
| 2km 竞品请求契约 | `skill-request.schema.json` |
| 页面市场证据契约 | `market-evidence-collection/v2`；标准路径为全量地图 Playwright Profile + Ego Lite OTA Profile；Ui.Vision/OpenCLI 携程实时价（内置离线 Scrapling DOM 解析）仅为可选 P2 扩展，Kimi WebBridge/crawl4ai/xcrawl 可替换 |
| 竞品调研交付 | `--format html` 的独立单文件 HTML，含视觉竞品对标区 |
| 飞书多维表格交付 | `--format bitable` 的标准八表无凭证 manifest `1.3`；宿主应用它，不重复计算，并将载荷写入、市场、ADR 与投决范围分开表达 |

采用 `MAJOR.MINOR.PATCH`：不兼容的请求/输出契约变更升 MAJOR，向后兼容的新
能力升 MINOR，修复升 PATCH；不改变契约、脚本逻辑或计算口径的入口文案/上下文
压缩也升 PATCH。每次发布同时更新包内 `VERSION`、`CHANGELOG.md`
和 `scripts/run.py` 输出的 `skill_version`，运行核心测试与 Skill 结构校验，并从
已验证 tag 打包唯一的 Skill 目录。页面回执 HMAC 密钥是宿主部署配置，不随包、测试
样例或 Git 发布。页面采集源码和锁定依赖随 Skill 发布，但来源
会话/凭证、持久化和消息通道仍由宿主拥有。
