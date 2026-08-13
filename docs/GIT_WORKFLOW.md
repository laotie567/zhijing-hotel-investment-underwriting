# Git 工作流

## 1. 仓库边界

纳入版本控制：

- 当前生产 Skill 的代码、Schema、方法论、样例和测试；
- 根目录项目文档、变更记录与包内版本文件。

不纳入版本控制：

- 历史客户 Excel、Word、合同和原始页面；需要追溯时从 Git 历史或受控业务档案取得；
- 测试输出、日志、缓存和临时文件；
- 密钥、`.env` 和授权凭证；
- 可从 tag 重新生成的 ZIP 发布包。

当前 Skill 只依赖 Python 标准库。不要把地图/OTA SDK、爬虫、数据库、审批或
消息平台代码加入此仓库；它们属于宿主。

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
git add -A

python3 /path/to/skill-creator/scripts/quick_validate.py hotel-investment-underwriting

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s hotel-investment-underwriting/tests -p 'test_*.py'

git diff --cached --check
```

归档边界测试使用暂存树，故 `git add -A` 必须在测试前执行。若修改冻结财务机械，
额外执行 Golden Master；不要新增状态、审批、回放或爬虫实现到当前发布路径。发布
归档采用精确白名单，新增包内文件时必须同时说明业务必要性、更新归档测试并复核
发布边界。

## 5. 发布与 GitHub

```bash
git commit -m "release: vX.Y.Z"
git tag -a vX.Y.Z -m "release vX.Y.Z"
git show --stat vX.Y.Z
git remote -v
git push origin HEAD:main
git push origin vX.Y.Z

git archive --format=zip --output hotel-investment-underwriting-vX.Y.Z.zip \
  vX.Y.Z hotel-investment-underwriting
shasum -a 256 hotel-investment-underwriting-vX.Y.Z.zip
gh release create vX.Y.Z hotel-investment-underwriting-vX.Y.Z.zip \
  --title "vX.Y.Z" --generate-notes
```

先确认 `origin` 指向获授权的私有 GitHub 仓库、分支保护已开启并且 tag 指向已验证
提交。若尚未配置 `origin`，必须由仓库所有者提供 GitHub 仓库 URL 和可见性，不能
猜测或自动创建远程仓库。将 ZIP 的 SHA-256 写入 GitHub Release 正文或作为同名
`.sha256` 附件；确认 Release 同时包含 ZIP 与校验值后才算完成发布。

## 6. 评审要求

公式、评分权重、合同口径、审批规则和证据状态的变更必须由业务负责人与技术负责人
双重评审。纯文案和格式修复可使用单人评审。
