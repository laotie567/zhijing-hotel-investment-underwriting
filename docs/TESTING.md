# 单一 Skill 测试与发布验收

## 必测行为

- 未确认点位不生成竞品结论；
- 只保留 2km 内、与中心同一地图 provider、营业中、主营电竞住宿且来源完整的正式竞品；
- 重复 `provider_place_id`、缺少来源和不完整采集阻断正式结论；
- 同一酒店的多条房型报价只计一个独立样本；仅相同入住日期、晚数、人数和 CNY 条件下的中/高置信度报价可计入，至少三家独立竞品才产生 ADR 参考；
- `run.py` 同时返回竞品分析和财务预评估，且不自动改写收入假设；
- 未知或非法 `project_input` 字段在公共入口失败；
- `calculate.py` 不能作为独立 CLI 绕过 2km 阶段；
- 静态回本月数必须复现历史“初投 ÷ 首年平均月经营净现金”口径，并同时返回保守向上取整月数；首年经营净现金非正时不得伪造回本月数；
- `--format html` 生成移动端可读的独立 HTML，包含竞品房型/报价表、独立视觉竞品对标区、已计算的月度回本表和已提供的内嵌图片；无图片时明确提示补证，不加载外部脚本、样式或图片，并保留 `pre_evaluation_only` 结论范围；
- 财务 Golden Master 和核心回归保持通过。

## 命令

```bash
git add -A

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s hotel-investment-underwriting/tests -p 'test_*.py'

python3 /path/to/skill-creator/scripts/quick_validate.py hotel-investment-underwriting
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
- [ ] 用脱敏完整请求分别验证 JSON、Feishu 和 HTML 输出；
- [ ] 在不具备 Skill 目录的浏览器环境打开 HTML，验证文字、表格和内嵌图片可见；
- [ ] 生产 ZIP 只包含唯一 Skill 的运行文件和包内 `VERSION`；
- [ ] 不含密钥、历史客户资料、测试、样例、旧包或历史 ZIP；
- [ ] `VERSION`、`CHANGELOG.md` 和输出 `skill_version` 已同步更新；
- [ ] 以已验证 tag 打包，计算 ZIP 的 SHA-256，并在 GitHub Release 附件中记录该值。
