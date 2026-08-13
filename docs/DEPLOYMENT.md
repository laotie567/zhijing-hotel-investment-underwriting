# 单一 Skill 生产部署

发布包只包含 `hotel-investment-underwriting/`：

- `SKILL.md`、`agents/openai.yaml`；
- `VERSION`；
- `scripts/run.py`、`input_contract.py`、`competitor_analysis.py`、`competitor_report.py`、`bitable_delivery.py`、`calculate.py`；
- `schemas/` 与运行说明所需的 `references/`。

测试、样例、根目录文档、生成结果和旧包均不会进入生产 ZIP。根目录与 Skill
目录的 `.gitattributes` 同时防止误用 `git archive HEAD` 时带入这些内容；归档测试
还对发布 ZIP 使用精确白名单，防止新的客户资料或无关文件随 Skill 一起发布。根
目录的 `.gitattributes` 仅是仓库打包保护文件，不属于实际交付物。

```bash
git archive --format=zip --output hotel-investment-underwriting-vX.Y.Z.zip \
  vX.Y.Z hotel-investment-underwriting
```

从已验证的 tag 打包，不从未提交工作区打包。解压后的入口是
`hotel-investment-underwriting/scripts/run.py`；包内 `VERSION` 与输出中的
`skill_version` 用于追溯本次运行。

## 运行要求

- Python 3.10+，只依赖标准库；
- 宿主安全注入已授权地图/证据工具的凭证；Skill 不读取或保存凭证；
- 宿主按需要保存请求、结果和发送消息；Skill 不要求数据库、状态目录、锁或守护进程。

## 宿主调用顺序

1. 确认一个 GCJ-02 物业中心点。
2. 从中心点的同一地图 `provider` 收集 2km 候选、每条候选的来源事实，以及所有报价共享的入住日期、晚数、人数和 CNY 条件。
3. 组装统一请求并调用 `scripts/run.py`。
4. 先读取 `workflow.status`，再展示竞品和财务结果。
5. 如需交付竞品调研，使用相同请求执行 `--format html` 并将标准输出保存为 `.html` 文件。
6. 如需交付飞书多维表格，使用相同请求执行 `--format bitable` 并将标准输出保存为 JSON 清单；已授权宿主按 `references/bitable-delivery.md` 创建/验证模板并写入。Skill 本身不持有飞书凭证或写入状态。

无法确认点位、候选证据不完整或重复 `provider_place_id` 时，Skill 返回
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
