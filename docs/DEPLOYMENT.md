# 单一 Skill 生产部署

发布包只包含 `hotel-investment-underwriting/`：

- `SKILL.md`、`agents/openai.yaml`；
- `VERSION`；
- `scripts/run.py`、`collect_market_evidence.py`、`market_evidence_contract.py`、`market_evidence_runtime.py`、`input_contract.py`、`competitor_analysis.py`、`competitor_report.py`、`bitable_delivery.py`、`calculate.py`；
- `collector/` 中锁定的 Playwright 与 Ego Lite 页面采集 Profile 源码；
- `schemas/` 与运行说明所需的 `references/`。

测试、样例、根目录文档、生成结果和旧包均不会进入生产 ZIP。根目录与 Skill
目录的 `.gitattributes` 同时防止误用 `git archive HEAD` 时带入这些内容；归档测试
还对发布 ZIP 使用精确白名单，防止新的客户资料或无关文件随 Skill 一起发布。根
目录的 `.gitattributes` 仅是仓库打包保护文件，不属于实际交付物。

```bash
git archive --format=zip --output hotel-investment-underwriting-vX.Y.Z.zip \
  vX.Y.Z hotel-investment-underwriting
```

从已验证的 tag 打包，不从未提交工作区打包。解压后先使用
`hotel-investment-underwriting/scripts/collect_market_evidence.py` 采集证据，
再使用唯一测算入口 `scripts/run.py`；包内 `VERSION` 与输出中的 `skill_version`
用于追溯本次测算运行。

## 运行要求

- Python 3.10+；核心测算只依赖标准库；
- 页面证据采集默认需要 Node 20+、`collector/package-lock.json` 和 Chromium；安装命令见 `references/market-evidence-collection.md`；
- Mac Mini/Hermes 在首次运行前必须执行 `python3 scripts/collect_market_evidence.py --preflight --all-engines`；Ego Lite 或 Kimi WebBridge 未安装/未连接时，按输出的 `install_hint` 安装并重启 Hermes。Ego Lite 仅用于本机 macOS 认证页面会话，不替代云端采集器；
- 宿主安全注入已授权页面来源会话/凭证；Skill 不读取或保存凭证；
- 宿主按需要保存请求、结果和发送消息；Skill 不要求数据库、状态目录、锁或守护进程。

## Mac Mini / Hermes 首次安装

在新主机解压发布 ZIP（或从授权 GitHub 仓库检出 tag）后，在包根目录运行：

```bash
cd hotel-investment-underwriting/collector
npm ci
npx playwright install chromium
cd ..
python3 scripts/collect_market_evidence.py --preflight --all-engines
```

`preflight` 不会自动安装浏览器扩展、读取 Cookie 或尝试登录。仅当本次选用的引擎为
`ready` 才能采集：缺少 **Ego Lite** 时按 `install_hint` 安装、完成其 onboarding 后重启
Hermes；使用 Kimi WebBridge 时还必须安装并连接扩展、再设置
`MARKET_EVIDENCE_KIMI_WEBBRIDGE_COMMAND`。未选用的 crawl4ai、xcrawl、OpenCLI
适配器可以保持 `action_required`，不会妨碍已就绪的 Playwright/Ego Lite 链路。

生产宿主只调用 CLI 或只监听本机的 HTTP 接口，绝不将浏览器操作转嫁给 Codex
Computer Use：

```bash
python3 scripts/collect_market_evidence.py \
  --engine ego-browser --serve 127.0.0.1:8791
```

Ego Lite 登录态仅驻留在这台 Mac Mini。若 OTA 显示“登录看低价”、验证码或售罄，采集器
返回 `partial`；管理员在 Ego Lite 完成正常登录后重跑相同请求，不能以无口径列表价替代。

## 宿主调用顺序

1. 先用 `360-map-v1` 采集中心点和全量同源 2km 候选；再把明确选出的 `benchmark_selected` 候选及其 OTA 实体映射交给 `ctrip-hotel-v1` 或其他明确的报价 Profile。它返回房型/图片、报价覆盖度和页面回执。
2. 只有全量候选以及本次标杆集所需的房型、图片、同条件报价覆盖度均为 `complete` 时，才可把 `competitor_analysis.collection_status` 设为 `complete`；否则保留 `partial`。
3. 把 `--format skill-patch` 输出与项目财务输入组装为统一请求并调用 `scripts/run.py`。
4. 先读取 `workflow.status`，再展示竞品和财务结果。
5. 如需交付竞品调研，使用相同请求执行 `--format html` 并将标准输出保存为 `.html` 文件。
6. 如需交付飞书多维表格，使用相同请求执行 `--format bitable` 并将标准输出保存为 JSON 清单；先检查 `delivery_gate.final_delivery_eligible`。为 `false` 时只能写入带待补记录的草稿，不能称为完整交付；为 `true` 时仍先写入“待写入核验”，只有宿主上传并读回所有附件、关联和记录后才更新为“可交付”。已授权宿主按 `references/bitable-delivery.md` 创建/迁移模板并写入。Skill 本身不持有飞书凭证或写入状态。

无法确认点位、页面采集失败/不完整、OTA 映射不完整、候选证据不完整或重复 `provider_place_id` 时，Skill 返回
`pre_evaluation_only`，而不是伪造完整的竞品结论。

```bash
python3 hotel-investment-underwriting/scripts/run.py \
  --input /path/to/skill-request.json \
  --defaults hotel-investment-underwriting/references/benchmark-defaults.json \
  --format json
```

```bash
python3 hotel-investment-underwriting/scripts/run.py \
  --input /path/to/skill-request.json \
  --defaults hotel-investment-underwriting/references/benchmark-defaults.json \
  --format html > /path/to/competitor-research.html
```

该 HTML 不需要 Python、Skill 目录或网络资源来展示内容；样式和已提供的房图都在文件内。浏览器打开来源链接时才需要网络。

```bash
python3 hotel-investment-underwriting/scripts/run.py \
  --input /path/to/skill-request.json \
  --defaults hotel-investment-underwriting/references/benchmark-defaults.json \
  --format bitable > /path/to/bitable-delivery.json
```

该清单不依赖于当前机器上的飞书 CLI、环境变量或网络连接；它可由任何已授权的
Feishu 宿主应用到标准 Base。基于表名和逻辑记录键完成幂等写入，随后解析关联并
上传 `data_uri` 图片；不可用来源 URL 代替图片数据。

## 发布检查

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py hotel-investment-underwriting

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s hotel-investment-underwriting/tests -p 'test_*.py'

git archive --format=tar HEAD | tar -tf -
```

归档边界测试读取 Git 暂存树，并以与生产命令一致的 `hotel-investment-underwriting/`
子目录归档；运行完整测试前先执行 `git add -A`，确保它验证即将提交的发布内容。
完成测试、提交和 tag 后，再执行上面的 tag 打包命令。

使用一份脱敏完整请求演练 JSON、Feishu 与 HTML 输出。HTML 应在不含 Skill
目录的设备上打开，确认文字、表格和已内嵌图片可见。地图、证据和消息通道的
连通性由宿主单独验收。
