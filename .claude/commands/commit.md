分析工作区改动，按主题拆分为多个 conventional commits 并提交，默认不 push。

用户可通过 `<args>` 传入提示，例如：
`/commit 全部合并为一个` → 不拆分，强制单 commit
`/commit fix(rag)` → 提示主题倾向（仅供分析参考，仍需按实际差异拆分）
`/commit push` → 提交完成后自动 push 到 origin

若未传入参数，则按"主题拆分 + 不 push"默认行为执行。

---

## 执行步骤

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

---

## 注意事项

- **commit message 标题用英文，body 用中文**：标题让 GitHub UI / changelog tooling 友好，body 给团队讲清楚为什么改
- **不要把"什么时候改的"写进 message**（git 自带时间戳）
- **不要在 body 里复制粘贴 diff**，用文字描述意图即可
- 每个 commit 完成后再开始下一个，不要积攒；中途 commit 失败立即停下问用户
- 如果用户在某个 commit 后说"撤销"，用 `git reset --soft HEAD~1` 退回到 staging 区（保留改动），**不要** `--hard`
- `.claude/agents/` 与 `.claude/commands/` 下的 skill 文件**应该提交**（项目级共享），但 `.claude/settings.local.json` 与 `.claude/agent-memory/` **不能提交**（已在 .gitignore，但仍需警觉）
