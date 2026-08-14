# 单一 Skill 生产部署

发布包只包含 `hotel-investment-underwriting/`：

- `SKILL.md`、`agents/openai.yaml`；
- `VERSION`；
- `scripts/run.py`、`collect_market_evidence.py`、`market_evidence_contract.py`、`market_evidence_runtime.py`、`ctrip_dom_parser.py`、`input_contract.py`、`competitor_analysis.py`、`competitor_report.py`、`bitable_delivery.py`、`calculate.py`；
- `collector/` 中锁定的 Playwright、Ego Lite 与 Ui.Vision+OpenCLI 携程实时价采集 Profile 源码，以及仅离线解析用的 Scrapling 锁定依赖和 Ctrip 元素注册表；
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

- Python 3.10+；核心测算只依赖标准库。选择 `ctrip-live-rates` 时，另在项目本地虚拟环境中安装锁定的 Scrapling **解析器依赖**；它不含浏览器、抓取器、代理或凭证处理；
- 页面证据采集默认需要 Node 20+、`collector/package-lock.json` 和 Chromium；安装命令见 `references/market-evidence-collection.md`；
- Mac Mini/Hermes 的默认验收先执行 `python3 scripts/collect_market_evidence.py --preflight --engine ego-browser`；地图池另按 Playwright 安装要求验收。Ego Lite 未安装/未登录时，按输出的 `install_hint` 处理并重启 Hermes。Ui.Vision+OpenCLI、OpenCLI Ctrip 搜索命令或 Kimi WebBridge 只在宿主显式启用对应可选 Profile 时才需预检；Ego Lite 与可选扩展都仅用于本机 macOS 认证页面会话，不替代云端采集器；
- 宿主安全注入已授权页面来源会话/凭证；Skill 不读取或保存凭证；
- 宿主按需要保存请求、结果和发送消息；Skill 不要求数据库、持久状态目录或守护进程。`ctrip-live-rates` 仅在单次运行期间创建并删除临时浏览器互斥锁。

## Mac Mini / Hermes 首次安装

在新主机解压发布 ZIP（或从授权 GitHub 仓库检出 tag）后，在包根目录运行：

```bash
cd hotel-investment-underwriting/collector
npm ci
npx playwright install chromium
cd ..
python3 scripts/collect_market_evidence.py --preflight --engine playwright
python3 scripts/collect_market_evidence.py --preflight --engine ego-browser
```

`preflight` 不会自动安装浏览器扩展、读取 Cookie 或尝试登录。仅当本次选用的引擎为
`ready` 才能采集：缺少 **Ego Lite** 时按 `install_hint` 安装、完成其 onboarding 后重启
Hermes。Ui.Vision+OpenCLI、Kimi WebBridge、crawl4ai、xcrawl 等可选扩展可以保持
`action_required`，不会妨碍已就绪的 Playwright/Ego Lite 标准链路。

如需 P2 强校验而选择**可选**的携程实时价 Profile，才需要单独的 Chrome `ctrip-price-worker` Profile，并在该
Profile 中安装 OpenCLI Browser Bridge 和 Ui.Vision；管理员正常登录携程、完成验证码和
Ui.Vision 的本机配对。再安装固定 Bridge 版本：

```bash
npm install -g uivision-mcp-bridge@1.1.1
python3 scripts/collect_market_evidence.py --preflight --engine ctrip-live-rates
```

当前 OpenCLI 的 `browser … bind` 在同时连接多个 Browser Bridge Profile 时会拒绝选择标签页。
因此实时价 Worker 的硬性前提是：**仅** `ctrip-price-worker` 启用并连接 OpenCLI Browser
Bridge，且执行 `opencli profile use ctrip-price-worker`；在其他 Chrome Profile 中禁用该扩展。
预检会在打开携程页之前验证这一条件，并给出可执行的 `install_hint`。

实时价采集严格由 Ui.Vision 改变页面状态、OpenCLI 只读 Network/DOM，Scrapling 只离线解析一个受大小限制的已观察房型 DOM 片段；预检还验证本机
`opencli ctrip search --help`，以保证自动映射所需的 Ctrip 命令真实可用。回执不含 Cookie、
请求头、令牌或原始响应 body。未登录、验证码、房源映射歧义、无库存和页面结构变动（`DOM_SCHEMA_DRIFT`）会
返回明确的 `collection_issues`，而非静默写入空报价或伪 ADR。

生产宿主以 Playwright 地图池与 Ego Lite OTA Profile 作为标准链路，只调用 CLI 或只监听本机的 HTTP 接口，绝不将浏览器操作转嫁给 Codex Computer Use：

```bash
python3 scripts/collect_market_evidence.py \
  --engine ego-browser --serve 127.0.0.1:8791
```

Ego Lite 登录态仅驻留在这台 Mac Mini。若 OTA 显示“登录看低价”或验证码，采集器返回
`partial`；若明确售罄/不接受预订，则写入 `NO_INVENTORY`，其整体状态仍由房型、图片等其余
覆盖度决定。管理员在 Ego Lite 完成正常登录后重跑相同请求，不能以无口径列表价替代。

## 宿主调用顺序

1. 标准路径先用 `360-map-v1` 采集中心点和全量同源 2km 候选，保存回执中的 `spatial_collection`；再把**全量**候选和这份原样 `candidate_pool` 交给 Ego `ctrip-hotel-v1`。该 Profile 要求显式 OTA 实体映射；只有显式启用的 P2 扩展 `ctrip-live-rates-v1` 才可按名称+城市唯一精确地自动映射。OTA 回执必须原样返回该池，且运行器拒绝引擎/Profile/中心/候选指纹不匹配。
2. `competitor_analysis.collection_status=complete` 只表示全量 2km 空间候选已被证明完成。房型、图片、同条件报价的 `partial` 仍使**采集回执**为 `partial`，阻止 ADR 或完整交付，但不会把已完成的空间竞品集合降级为未完成。
3. 把 `--format skill-patch` 输出与项目财务输入组装为统一请求并调用 `scripts/run.py`。
4. 先读取 `workflow.status`，再展示竞品和财务结果。
5. 如需交付竞品调研，使用相同请求执行 `--format html` 并将标准输出保存为 `.html` 文件。
6. 如需交付飞书多维表格，使用相同请求执行 `--format bitable` 并将标准输出保存为 JSON 清单；先检查 `delivery_gate.final_delivery_eligible`。为 `false` 时只能写入带待补记录的草稿，不能称为完整交付；为 `true` 时仍先写入“待写入核验”，只有宿主上传并读回所有附件、关联和记录后才更新为“可交付”。已授权宿主按 `references/bitable-delivery.md` 创建/迁移模板并写入。Skill 本身不持有飞书凭证或写入状态。

无法确认点位、空间候选池不完整、候选证据不完整或重复 `provider_place_id` 时，Skill 返回
`pre_evaluation_only`，而不是伪造完整的竞品结论。OTA 映射、图片或价格不完整会保留
已确认的空间结论，同时将缺口和不可用 ADR 清晰写入结果与交付物。

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
