# Git 工作流

## 1. 仓库边界

当前获授权的唯一 GitHub 远程仓库为
`https://github.com/laotie567/zhijing-hotel-investment-underwriting.git`。它是本 Skill
的新仓库，不得推送到此前的历史项目仓库。执行任何 `push`、`merge`、tag 或 Release
操作前先做精确校验：

```bash
test "$(git remote get-url origin)" = \
  "https://github.com/laotie567/zhijing-hotel-investment-underwriting.git"
git fetch origin --prune
git branch -vv
```

若 URL 不一致、`origin` 不存在或当前仓库不在该远程可见范围内，立即停止并由仓库
所有者修正；禁止通过猜测、覆盖远程或复用旧仓库 URL 解决。

纳入版本控制：

- 当前生产 Skill 的代码、Schema、方法论、样例和测试；
- 根目录项目文档、变更记录与包内版本文件。

不纳入版本控制：

- 历史客户 Excel、Word、合同和原始页面；需要追溯时从 Git 历史或受控业务档案取得；
- 测试输出、日志、缓存和临时文件；
- 密钥、`.env` 和授权凭证；
- 可从 tag 重新生成的 ZIP 发布包。

`.gitignore` 防止日常误加入；根目录与 Skill 目录的 `.gitattributes` 还会把 Office 文档、
PDF 和普通图片从任何 Git archive 排除，防御一次 `git add -f`。这不是保存客户资料的替代
机制：发现已跟踪的客户文件时，先停止发布、确认精确路径并用常规评审移除，再重新验证归档。

核心测算只依赖 Python 标准库。唯一允许进入发布路径的外部采集运行时是
`collector/` 中锁定、无界面且有 `market-evidence-collection/v2` 回执的页面
Profile；不要加入地图/OTA SDK、未验证的爬虫、数据库、审批或消息平台代码。

## 2. 分支

- `main`：远程仓库的可发布集成基线。
- `codex/<short-name>`：开发、修复或文档分支。
- `release/<version>`：可选的发布收口分支。

禁止在已发布 tag 上重写历史。在共享仓库中禁止对 `main` 强制推送。

## 3. 提交规范

提交使用下列前缀：

- `feat:` 新业务能力；
- `fix:` 错误修复；
- `docs:` 文档；
- `test:` 测试；
- `refactor:` 不改变业务语义的结构调整；
- `chore:` 工具、Git 和打包；
- `release:` 发布基线。

提交必须聚焦于一个逻辑变更，不将业务公式、大量格式化和无关文档混在同一提交。
破坏性变更在提交正文中说明迁移方法。

## 4. 变更提交前

```bash
git status --short
git diff --check
git diff --stat
# 仅暂存本次审核过的生产代码、测试与文档；不要把临时结果或客户资料一并加入索引。
git add <intended-files>

python3 /path/to/skill-creator/scripts/quick_validate.py hotel-investment-underwriting

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s hotel-investment-underwriting/tests -p 'test_*.py'

git diff --cached --check
```

归档边界测试使用暂存树，故明确的发布文件必须在测试前暂存；测试以生产子目录 archive
做精确白名单比对，并额外核验根 archive 的客户 Office/图片排除属性。若修改冻结财务机械，
额外执行 Golden Master；不要新增状态、审批、回放或未纳入页面采集契约的爬虫实现
到当前发布路径。发布归档采用精确白名单，新增包内文件时必须同时说明业务必要性、
更新归档测试并复核发布边界。

## 5. 发布与 GitHub

```bash
# 在已经验证并通过测试的 codex/<short-name> 分支上提交。
git commit -m "release: vX.Y.Z"
git fetch origin --prune
git switch main
git pull --ff-only origin main
git merge --ff-only codex/<short-name>
git push origin main

# tag 必须指向已推送到 main 的同一提交。
git tag -a vX.Y.Z -m "release vX.Y.Z"
git show --stat vX.Y.Z
git push origin vX.Y.Z

git archive --format=zip --output hotel-investment-underwriting-vX.Y.Z.zip \
  vX.Y.Z hotel-investment-underwriting
shasum -a 256 hotel-investment-underwriting-vX.Y.Z.zip
gh release create vX.Y.Z hotel-investment-underwriting-vX.Y.Z.zip \
  --title "vX.Y.Z" --generate-notes
```

先确认 `origin` 通过上一节的精确新仓库校验、分支保护已开启并且 tag 指向已验证
的 `main` 提交。若尚未配置 `origin`，必须由仓库所有者提供 GitHub 仓库 URL 和
可见性，不能猜测或自动创建远程仓库。将 ZIP 的 SHA-256 写入 GitHub Release 正文或作为同名
`.sha256` 附件；确认 Release 同时包含 ZIP 与校验值后才算完成发布。

## 6. 评审要求

公式、评分权重、合同口径、审批规则和证据状态的变更必须由业务负责人与技术负责人
双重评审。纯文案和格式修复可使用单人评审。
