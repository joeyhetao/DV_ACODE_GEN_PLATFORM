分析工作区改动，按主题拆分为多个 conventional commits 并提交，默认不 push。

用户可通过 `<args>` 传入提示，例如：
`/commit 全部合并为一个` → 不拆分，强制单 commit
`/commit fix(rag)` → 提示主题倾向（仅供分析参考，仍需按实际差异拆分）
`/commit push` → 提交完成后自动 push 到 origin

若未传入参数，则按"主题拆分 + 不 push"默认行为执行。

---

## 执行步骤

### 第零步：上库前置审计（强制，无法跳过）

提交任何 commit 之前，先做三轮安全审计。任一轮发现问题都**硬停**，不得继续后续步骤，先向用户报告并等明确处置指令。

#### 0a. 未追踪文件分流

```bash
git status --short | grep "^??"
```

对每个 `??` 文件（即 untracked 但未被 `.gitignore` 拦截的文件），按下表归类后向用户**输出分流方案**等确认：

| 类别 | 判断特征 | 默认处理 |
|---|---|---|
| **应追踪** | 源代码（.py / .ts / .tsx / .js / .yaml / .sh / Dockerfile / .conf / .toml / .json）<br>项目文档（README/CHANGELOG/PRD/ARCHITECTURE/CONTRIBUTING/docs/*.md）<br>配置文件（docker-compose*.yml / nginx*.conf / pyproject.toml / package.json / tsconfig.json）<br>新增模板（template_library/**/*.yaml） | 加入下一步 commit 候选 |
| **应忽略**（但 .gitignore 漏了） | node_modules/ / dist/ / __pycache__/ / .venv/ / *.pyc / coverage/ / hf_cache/ / models/ | **先补 .gitignore**，提示用户单独 commit gitignore，不要把这些文件 add |
| **可疑—需用户决定** | 文件名含 `temp_` / `tmp_` / `scratch_` / `draft_` / `wip_` / `personal_` / `test_local`<br>未配套被引用的孤立脚本<br>无后缀且非典型项目文件 | **报告给用户**：列出文件名 + 内容前 5 行，等用户决定 commit / ignore / 删除 |
| **绝对禁止** | 文件名含 `secret` / `credential` / `private_key` / `id_rsa` / `*.pem` / `*.key` / `*.crt` / `.env`（任何变体，包括 `.env.production` / `.env.local`） | **拒绝 commit + 立刻报警**：警告用户该文件是敏感数据，建议加入 .gitignore；若已是 .gitignore 漏了，先补 |

输出示例：

```
未追踪文件分流：
✓ 应追踪（自动加入候选）：
  - backend/app/services/new_feature.py
  - docs/feature-spec.md

⚠ 可疑（请确认）：
  - scratch_test.sh    （文件名含 "scratch_"，请确认是临时脚本还是要保留？）

✗ 绝对禁止：
  - secrets.json       （含 "secret" 关键词，已自动跳过；建议加入 .gitignore）

是否按此分流执行？
```

#### 0b. 敏感内容扫描

对**所有候选 staged 文件**（修改的 + 经 0a 确认要追踪的）做内容扫描，检查以下模式：

| 类别 | 正则 / 关键词 | 处置 |
|---|---|---|
| 第三方 API Key | `sk-[A-Za-z0-9]{20,}` (OpenAI/智谱/Anthropic 等)<br>`ghp_[A-Za-z0-9]{36}` / `github_pat_[A-Za-z0-9_]{82}` (GitHub)<br>`xoxb-\d+-\d+-[A-Za-z0-9]+` (Slack)<br>`AKIA[0-9A-Z]{16}` (AWS Access Key) | **硬阻止**，定位到行，提示移到 .env |
| AWS Secret | `aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}` | **硬阻止**，定位到行 |
| 私钥块 | `-----BEGIN [A-Z ]*PRIVATE KEY-----` | **硬阻止**，建议挪到 secrets/ 目录并加 .gitignore |
| JWT Token | `eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}` | **硬阻止**，定位到行 |
| 硬编码密码 | `(password\|passwd\|secret\|pwd)\s*[:=]\s*["'][^"'$\{][^"']{4,}["']`<br>排除：值是 placeholder（含 `change-me` / `example` / `your-` / `xxx` / `<...>` / `${...}` / `os.environ`）<br>排除：`SUPER_ADMIN_PASSWORD` 在 config.py 里的开发默认值（已是已知非生产值） | **警告 + 等用户确认**，可能是占位符 |
| 内部 IP / 主机名 | `\b(?:10\\.\|172\\.(?:1[6-9]\|2[0-9]\|3[01])\.\|192\\.168\\.)\d+\\.\d+\\.\d+`<br>排除：`192.168.1.1` / `10.0.0.1` 等示例 IP；排除 docker-compose 内部 hostname（`postgres` / `redis` / `qdrant` / `backend` 等） | **警告 + 等用户确认**，可能是公司内网地址 |
| 个人路径 | `[Cc]:[\\\/]Users[\\\/]\w+`<br>`/Users/\w+`<br>`/home/[\w\-]+` | **警告 + 等用户确认**，是否要替换成相对路径 |
| 个人邮箱（非 Co-Authored-By） | `[\w\.\-]+@(?!example\.com\|test\.com\|noreply\.\|anthropic\.com)[\w\.\-]+\.\w+` | **警告**，可能含真实人名 |

**扫描方法**：用 Grep 工具对每个候选文件运行上述模式，命中则向用户输出：
```
⛔ 检测到敏感内容，已阻止 commit：

  文件：backend/app/services/llm/openai_compat_client.py
  行 12：    api_key="sk-abc123def456ghi789jkl012mno345pqr678stu"
            ↑ 第三方 API Key 直接硬编码

  建议：改为 api_key=os.getenv("LLM_API_KEY")，并在 .env 中配置。
        请修复后重试 /commit。
```

发现敏感内容时**只报告，不自动修改**——修改决策权在用户。

#### 0c. 已追踪文件中的"应忽略"模式

```bash
git ls-files | grep -E "(\.env$|\.env\.[^e]|\.pem$|\.key$|\.crt$|credentials|node_modules|__pycache__|\.pyc$|\.DS_Store|\.swp$)"
```

如有命中，说明历史上误追踪过敏感/构建文件，向用户报告并建议：
1. `git rm --cached <file>` 从索引移除（保留磁盘文件）
2. 补 .gitignore 防止下次再被加回
3. 把这两步作为一个独立的 `chore: cleanup wrongly tracked` commit

---

**第零步审计全部通过后**，向用户输出一行简报（例：`审计通过：未追踪 2 个新文件已分类，6 个修改文件无敏感内容。开始第一步…`），然后自动进入第一步。

---

### 第一步：采集工作区状态

```bash
git status --short
git diff --stat
git log --oneline -10
```

读取这三项后再决定如何拆分。**不要**直接 `git add .` 或 `git commit -a`。

如果工作区无改动（git status 为空），向用户回复"工作区干净，无需提交"并退出。

### 第二步：按文件分析差异并归类主题

对 `git status` 列出的每个文件，逐一执行 `git diff <file>`（或 `--stat` + 抽样查看），按以下规则归类：

#### 主题分类规则（基于 CONTRIBUTING.md §5）

| Type | 用于 | 典型 scope |
|---|---|---|
| `feat` | 新增功能、新行为 | `engine` `llm` `pipeline` `rag` `api` `frontend` `template` |
| `fix` | Bug 修复、行为修正 | `engine` `llm` `rag` `qdrant` `infra` `frontend` `db` `auth` |
| `docs` | 仅文档变更（README/PRD/ARCHITECTURE/CHANGELOG/CONTRIBUTING/docs/） | 无 scope 或 `deploy` |
| `refactor` | 代码重构无功能变更 | 同 feat |
| `test` | 添加/修改测试 | 同 feat |
| `chore` | 依赖、构建、配置、清理未用 imports、模板字段更新 | `deps` `deploy` `frontend` `templates` |
| `perf` | 性能优化 | 同 feat |
| `ci` | CI/CD 配置 | 无 scope |

#### 同主题归并的判断（避免拆得过碎）

以下情况**应合并到同一 commit**：
- 同一新功能涉及的 schema + service + 前端 UI（例：`feat(llm)` 包含 client + base + schema + AdminLLMPage）
- 同一 bug fix 涉及的多个文件（例：`fix(infra)` 包含 nginx.conf + frontend/nginx-frontend.conf）
- 多个文件同样性质的小清理（例：6 个前端页同时删未用 imports → 1 个 `chore` commit）

以下情况**应拆为独立 commit**：
- 不同根因的 fix（例：rag 失败和 nginx 路由问题是两件事，拆开）
- feat 与 fix 同时存在（一个 commit 只解决一件事）
- 文档变更与代码变更（docs 单独成 commit，便于后续 cherry-pick）

#### 拆分方案预览

主题归类完成后，**先向用户输出拟拆分方案**（编号清单 + 每个 commit 涉及的文件 + 一句话主题），等用户确认或调整后再开始 add/commit。

例：

```
拟拆分为 3 个 commit：
1. feat(llm): two-step calling for thinking models
   - backend/app/services/llm/openai_compat_client.py
   - backend/app/services/llm/base.py
   - backend/app/schemas/intent.py
2. fix(rag): Stage3 graceful degradation
   - backend/app/services/rag/engine.py
   - backend/app/services/rag/stage1_hybrid.py
3. chore: remove unused imports
   - frontend/src/components/MainLayout.tsx
   - frontend/src/pages/Admin/AdminLLMPage.tsx

是否按此方案提交？(/commit 全部合并为一个 可强制单 commit)
```

若用户传入 `全部合并为一个` / `单 commit` 等参数，跳过此步骤直接合为 1 个 commit。

### 第三步：逐个执行 commit

对每个拆分主题，依次：

1. **stage 文件**（用具体文件名，禁止 `git add .` / `git add -A`）
   ```bash
   git add <file1> <file2> ...
   ```

2. **commit 消息**（HEREDOC 风格，标题英文、body 中文、必带 Co-Authored-By trailer）
   ```bash
   git commit -m "$(cat <<'EOF'
   <type>(<scope>): <英文一句 subject，<70 字符>

   <中文 body：解释为什么改、改动要点、已知影响>
   - 要点 1
   - 要点 2

   Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
   EOF
   )"
   ```

3. 单个 commit 完成后**回显** `git log -1 --format="%h %s"` 让用户看到结果

如果 commit 失败（pre-commit hook 报错等），**修复底层问题后创建新 commit**，绝不 amend 已失败的 commit（pre-commit 失败时 commit 实际未发生，amend 会改到上一个）。

### 第四步：提交完成后的状态汇报

全部 commit 完成后输出：

1. 本次新增 commit 列表（`git log <prev_HEAD>..HEAD --oneline`）
2. 工作区是否完全清理（`git status --short` 为空验证）
3. 是否已 push（默认未 push，提示用户如需 push 显式说明）

### 第五步（可选）：push

仅当用户传入 `push` 参数 **或** 提交后明确说"推上去"时执行：

```bash
git push
```

push 前确认：
- 当前分支不是 main/master 时无需确认；是 main/master 时 **必须先向用户确认一次**（再次确认才 push，避免误推到主干）
- 远程是否存在该分支的 tracking（`git branch -vv` 看是否有 `[origin/...]`）；无则用 `git push -u origin <branch>`

---

## 安全约束（不可违反）

| 禁止 | 替代 |
|---|---|
| `git add .` / `git add -A` | 总是用具体文件名 |
| `git commit --amend`（除非用户明确要求） | 创建新 commit |
| `git push --force` / `--force-with-lease`（除非用户明确要求） | 普通 push，遇冲突先 fetch+rebase |
| `--no-verify` skip pre-commit/commit-msg hook | 修复 hook 报错的根因 |
| commit message 不带 Co-Authored-By trailer | 永远附上 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` |
| 提交敏感文件（.env, *.key, *.pem, .claude/settings.local.json, credentials*） | 跳过并在汇报中提示用户加 .gitignore |
| 不读 diff 直接 commit | 至少 `git diff --stat` 确认范围 |
| **跳过第零步审计直接进入 commit 流程** | 即使用户传 `push` / `全部合并` 等参数，第零步也必须先跑完；审计有"绝对禁止"或"硬阻止"项时**禁止**继续，等用户处置 |
| 自动修改用户的源代码（即使是为了消除敏感内容警告） | 只报告位置 + 建议；改不改、怎么改由用户决定 |

---

## 注意事项

- **commit message 标题用英文，body 用中文**：标题让 GitHub UI / changelog tooling 友好，body 给团队讲清楚为什么改
- **不要把"什么时候改的"写进 message**（git 自带时间戳）
- **不要在 body 里复制粘贴 diff**，用文字描述意图即可
- 每个 commit 完成后再开始下一个，不要积攒；中途 commit 失败立即停下问用户
- 如果用户在某个 commit 后说"撤销"，用 `git reset --soft HEAD~1` 退回到 staging 区（保留改动），**不要** `--hard`
- `.claude/agents/` 与 `.claude/commands/` 下的 skill 文件**应该提交**（项目级共享），但 `.claude/settings.local.json` 与 `.claude/agent-memory/` **不能提交**（已在 .gitignore，但仍需警觉）
