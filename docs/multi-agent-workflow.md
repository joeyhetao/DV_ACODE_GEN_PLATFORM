# Multi-Agent 协同工作流操作手册

适用对象：在本仓库做一个 ticket（需求 / bug fix / 重构）的人。

本手册告诉你**怎么用** 4-agent 工作流跑完一个 ticket，不解释为什么这么设计 —— 设计动机看 [docs/spec_schema.md](spec_schema.md) 和 PR #1 / #2 / #3 的 commit message。

---

## 0. 什么时候用 / 什么时候别用

**用本工作流**：

- 一个 ticket 既改代码又改文档（PRD/ARCH/README/CHANGELOG/CONTRIBUTING）
- 需要 spec 沉淀决策、回头能查（团队协作场景）
- 改动相对独立、有明确边界（不是大重构）

**不用、直接在 develop 上干**：

- 只动 README / 一个 typo / 改个注释 —— 杀鸡用牛刀
- 紧急 hotfix（走 `hotfix/` 分支，hook 允许跨 zone 编辑）
- 探索性试错（先在本地玩通了再决定要不要正式立项）

---

## 1. 先决条件（首次使用必读）

只需做一次。

### 1.1 安装 GitHub CLI 并登录

`/open-pr` 调用 `gh pr create`，没装会 abort。

**Windows**（如果你的 Claude Code 跑在 Windows Git Bash 里）：

1. https://cli.github.com/ 下载安装 → 默认装到 `C:\Program Files\GitHub CLI\`
2. 把 `C:\Program Files\GitHub CLI` 加进 **User PATH**：Win+R → `sysdm.cpl` → Advanced → Environment Variables → User 段 `Path` → Edit → New → 输入路径 → 一路 OK
3. **完全关闭 VS Code 和所有终端**（PATH 改动对已运行的进程无效），重新打开
4. 新终端跑 `which gh`，应输出 `/c/Program Files/GitHub CLI/gh.exe`
5. `gh auth login` → 跟引导走（GitHub.com → HTTPS → Login with web browser）
6. `gh auth status` 应显示 `Logged in to github.com account <你的用户名>`

**WSL Ubuntu**：

```bash
sudo apt update && sudo apt install gh -y
gh auth login
```

### 1.2 确认 hook 已注册

```bash
cat .claude/settings.json | grep -A 3 PreToolUse
```

应该看到 `python "$CLAUDE_PROJECT_DIR/scripts/hooks/branch-scope-guard.py"`。没有的话说明设置文件被改坏了，对照 Day-1 PR #1 恢复。

### 1.3 开启 GitHub repo 的 Auto-merge（Opt-5 前置，一次性）

Settings → General → Pull Requests → 勾选 ✅ **Allow auto-merge**

开启后 `/open-pr` 成功开 PR 后会自动运行 `gh pr merge --auto --squash`——无 branch protection 时立即 merge，有 CI 时等 check 通过后自动 merge。已完成此设置可跳过。

### 1.4 验证 scaffold 安装齐备

```bash
ls .claude/agents/requirements-analyst.md \
   .claude/agents/pr-creator.md \
   .claude/agents/code-review-expert.md \
   .claude/commands/plan-ticket.md \
   .claude/commands/review-pre-pr.md \
   .claude/commands/open-pr.md \
   .claude/commands/update-specs.md \
   .claude/commands/update-docs.md \
   .claude/commands/commit.md \
   docs/spec_schema.md \
   scripts/worktree-init.sh
```

任一缺失 = scaffold 没装齐，检查最新 develop 是否包含 PR #3 的合并 commit。

---

## 2. 四个角色一句话

| # | 角色 | 在哪里跑 | 什么时候触发 |
|---|---|---|---|
| 1 | `requirements-analyst` | 主会话（develop） | `/plan-ticket TICK-X "需求描述"` |
| 2 | `code-review-expert` | feat/docs 会话 | `/review-pre-pr` |
| 3 | `documenter`（既有 skill 复用，无 agent 文件） | docs 会话 | `/update-specs` + `/update-docs` |
| 4 | `pr-creator` | feat/docs 会话 | `/open-pr <feat\|docs>` |

"coder" 不是 agent —— 你和主 Claude 会话本身就是 coder。

---

## 3. 总流程图

```
主会话/develop ──────────────────────────────────────────────
│
│  你: /plan-ticket TICK-X "..."
│      │
│      ▼  ① requirements-analyst 写 .claude/plans/TICK-X.spec.md
│
│  你: 审 spec, 改 status: draft → accepted
│  你: scripts/worktree-init.sh TICK-X
│      │  创建 paired worktree, 复制 spec, 种子 handoff JSON
└────────┴────────────────┐
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
   feat 会话 / feature/TICK-X     docs 会话 / docs/TICK-X
   (在 ../-feat-TICK-X 起 claude)  (feature PR merge 后再起)
        │                                  │
        │ 编码（自然语言指挥）              │ git rebase origin/develop
        │ /review-pre-pr  ← ② code-review  │ /update-specs       ← ③ documenter
        │ /commit                          │ /update-docs        ← ③ documenter
        │ /open-pr feat   ← ④ pr-creator   │ /review-pre-pr (light)
        │                                  │ /commit
        │                                  │ /open-pr docs       ← ④ pr-creator
        ▼                                  ▼
   feature PR → 人审 → merge          docs PR → 人审 → merge
```

**关键**：如果 spec §8 的 `docs_targets` 是 `[]`（空数组），就**不需要走 docs 会话**，feature PR merge 完直接清理。

---

## 4. 分阶段操作手册

### 阶段 A：起 ticket（主会话，develop 分支）

**前置**：`git status` 应该 clean，`git symbolic-ref --short HEAD` 应该是 `develop`。

#### A.1 让分析师写 spec

在 Claude 会话里输入：

```
/plan-ticket TICK-X 一句话描述需求
```

例：

```
/plan-ticket AUTH-12 给 /generate 接口加 rate limit, 每用户每分钟 10 次, 超过返回 429 含 Retry-After
```

会发生：

- analyst subagent 启动，读 PRD.md / ARCHITECTURE.md 相关章节 + 仓库结构
- ~15-30s 后写出 `.claude/plans/TICK-X.spec.md`，status 是 `draft`
- 主会话返回 `SPEC_WRITTEN: <abs path>` + 下一步提示

#### A.2 人审 spec

打开 `.claude/plans/TICK-X.spec.md`（VS Code 默认隐藏 gitignored 文件，**用 Ctrl+P 输入 TICK-X 直接打开**）。

**必看 3 段**：

- **§2 Acceptance Criteria**：检查测试得了吗？是不是你真实想要的行为？
- **§6 Docs Impact**：哪些文档要改？分析师猜对了吗？
- **§8 Machine block**：`docs_targets` 决定后面需不需要 docs worktree；`affected_paths` 决定 ARCH §7 目录树是否要更新

**改不动的话**：直接告诉主 Claude 会话"spec §X 改成 Y"，它会帮你改。

**确认 OK 后**：手动把 frontmatter 的 `status: draft` 改成 `status: accepted`（或告诉主 Claude 会话"改 accepted"）。

#### A.3 创建 paired worktree

```bash
# 主 worktree 根目录下跑：
scripts/worktree-init.sh TICK-X
```

会创建：

```
../<repo>-feat-TICK-X   on branch feature/TICK-X  ← 编码用
../<repo>-docs-TICK-X   on branch docs/TICK-X     ← 文档用（可能不需要）
```

并自动把 spec.md 复制到两个 worktree 里，seed handoff `.code.md` / `.docs.md` 模板。

**docs_targets=[] 时**（纯代码 ticket），`worktree-init.sh` 只创建 feat worktree，会打印：

```
[worktree-init] docs_targets=[] — skipping docs worktree.
                If scope shifts mid-ticket, run: scripts/worktree-init.sh --add-docs TICK-X
```

阶段 C.5 docs 会话可直接跳过，feature PR merge 后直接清理。

---

### 阶段 B：编码（feat 会话）

#### B.1 打开 feat 会话

**关键：必须在新终端里 `cd` 到 feat worktree 再起 claude**，不能继续用主会话。

```bash
# WSL 终端：
cd /home/Administrator/DV_ACODE_GEN_PLATFORM-feat-TICK-X
pwd  # 必须输出含 -feat-TICK-X 的路径才对
claude
```

**怎么确认你在对的 worktree**：feat 会话起来后第一句话让它跑：

```
pwd && git symbolic-ref --short HEAD
```

期望输出：

```
/home/Administrator/DV_ACODE_GEN_PLATFORM-feat-TICK-X
feature/TICK-X
```

**输出不对 = 你 cd 没成功**（详见 §7 故障排查 "feat 会话在错的 worktree"）。

#### B.2 编码

告诉 feat 会话：

```
读 .claude/plans/TICK-X.spec.md，按 §4 Implementation Sketch 实现。
注意 §3 Out 的约束。
```

它会读 spec 然后开始改代码。你可以中途打断、修正方向、提问。**branch-scope-guard hook 会阻止它编辑 PRD/ARCH/README/CONTRIBUTING/CLAUDE.md 及 `docs/` 目录** —— 那些是 docs 会话的活，feat 会话改了会 BLOCK 报错。**例外**：`CHANGELOG.md` 在 `feature/*` / `fix/*` 分支已放开，coder 可直接追加条目。spec §8 `docs_targets=["CHANGELOG"]` 时走这个快捷路径，不需要单开 docs 会话。

#### B.3 自审

```
/review-pre-pr
```

会调起 code-review-expert subagent 对当前 diff（uncommitted + staged）做 6 维 review：correctness / security / performance / style / maintainability / error handling。

Review 报告末尾主 session 自动追加 **Severity Triage** 段（`MUST address before PR` / `SHOULD consider` / `NIT (skip unless trivial)`）——只需看 MUST 列表判断是否有阻塞问题，无需通读整份报告。

按 review 反馈改完后**再跑一遍** `/review-pre-pr` 确认。可以迭代任意次。

#### B.4 填 handoff JSON（**仅需手动填 docs_targets**）

**`/commit` 会自动派生并回写** `affected_paths`、`changelog`、`needs_migration` 到 `.claude/state/TICK-X.code.md`。**你只需手动填 `docs_targets`**，因为它是人意图，无法从代码推导。

打开 `.claude/state/TICK-X.code.md`（在主 worktree 的 `.claude/state/` 里），找 `## Handoff JSON` 段，填 `docs_targets`：

```json
{
  "ticket": "TICK-X",
  "docs_targets": ["PRD", "ARCHITECTURE", "CHANGELOG"],
  "changelog": { "type": "feat", "scope": "api" },
  "affected_paths": [],
  "needs_migration": false
}
```

跟 spec §8 的差别：**handoff 反映实际改动**，spec §8 反映计划。开发中范围漂了，以 handoff 为准。

`docs_targets=[]` 时这步可跳过（`/commit` 自动派生的其余字段已足够）。

#### B.5 commit + 开 PR

```
/commit          # 自动 conventional commit, 默认不 push
/open-pr feat    # 开 feature PR
```

`/open-pr feat` 会调起 pr-creator subagent：

- 读 spec §7 PR Body Template
- 读 git log + diff
- 拼 title 和 body
- 调用 `gh pr create`（**此时会弹权限确认框**，看清 title+body 再点允许）

返回 `PR_OPENED: <url>`，随后自动运行 `gh pr merge --auto --squash`——无 branch protection 时立即 merge，有 CI 时等 check 通过后自动 merge（需 §1.3 已开启 Allow auto-merge）。传 `--no-auto-merge` 跳过此步：`/open-pr feat --no-auto-merge`。

---

### 阶段 C：人审 + merge feature PR

去 GitHub 看 PR diff、merge。Squash and merge 是标准做法（与 PR #1/#2/#3/#4 一致）。

**如果 spec §8 `docs_targets=[]`**：跳到阶段 D 清理。

**如果 docs_targets 非空**：继续阶段 C.5。

#### C.5 docs 会话

```bash
# WSL 终端：
cd /home/Administrator/DV_ACODE_GEN_PLATFORM-docs-TICK-X
claude
```

docs 会话里：

```bash
# 先 rebase 到最新 develop（含刚 merge 的 feature commit）
git fetch origin
git rebase origin/develop
```

然后：

```
/update-specs       # 同步 ARCHITECTURE.md + PRD.md
/update-docs        # 同步 README.md + CHANGELOG.md + CONTRIBUTING.md
/review-pre-pr      # 轻量 review（docs 模式: 只查死链 + 风格）
/commit
/open-pr docs
```

`/update-specs` 和 `/update-docs` 都内置 Step 0.5：自动读 spec.md §6 + 对面 feat worktree 的 handoff JSON，**精准定位要改的章节**，不会把 PRD/ARCH 全文读一遍浪费 token。

人审 + merge docs PR。

---

### 阶段 D：清理（feature PR / docs PR merged 之后）

回到主 worktree：

```bash
cd /home/Administrator/DV_ACODE_GEN_PLATFORM
git checkout develop
git fetch origin
git pull --ff-only

# 删 worktree（注意：用 git worktree list 输出的完整路径）
git worktree remove "//wsl.localhost/Ubuntu-22.04/home/Administrator/DV_ACODE_GEN_PLATFORM-feat-TICK-X"
git worktree remove "//wsl.localhost/Ubuntu-22.04/home/Administrator/DV_ACODE_GEN_PLATFORM-docs-TICK-X"

# 删本地分支
git branch -d feature/TICK-X docs/TICK-X

# 删远端分支（如果 GitHub 没自动删）
gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/feature/TICK-X
gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/docs/TICK-X

# 删 spec 和 state 文件
rm -f .claude/plans/TICK-X.spec.md \
      .claude/state/TICK-X.code.md \
      .claude/state/TICK-X.docs.md

# 清远端 prune
git fetch origin --prune
```

`git status` 应 clean，`git worktree list` 只剩主 worktree。

---

## 5. 一个完整真实例子（拿 TEST-1 实际数据）

```bash
# 阶段 A
/plan-ticket TEST-1 给 backend/app/main.py 顶部加一行说明文件作用的注释
# → analyst 写 spec.md (docs_targets=[]，因为只是注释)
# → 人审，改 status: accepted
scripts/worktree-init.sh TEST-1

# 阶段 B
cd /home/Administrator/DV_ACODE_GEN_PLATFORM-feat-TEST-1
claude
> 读 spec.md，按 §4 实现
> /review-pre-pr      # 通过
> /commit             # → 18f68bc chore(engine): add header comment ...
> /open-pr feat       # → PR #4

# 阶段 C - 因为 docs_targets=[]，跳过

# 阶段 D
cd /home/Administrator/DV_ACODE_GEN_PLATFORM
git checkout develop && git pull
git worktree remove "//wsl.localhost/Ubuntu-22.04/home/Administrator/DV_ACODE_GEN_PLATFORM-feat-TEST-1"
git worktree remove "//wsl.localhost/Ubuntu-22.04/home/Administrator/DV_ACODE_GEN_PLATFORM-docs-TEST-1"
git branch -d feature/TEST-1 docs/TEST-1
rm -f .claude/plans/TEST-1.spec.md .claude/state/TEST-1.*.md
```

---

## 6. 各种命令速查表

```
# 主会话（develop）
/plan-ticket TICK-X "..."        # 起 ticket，写 spec
scripts/worktree-init.sh TICK-X  # 创建双 worktree

# feat 会话
/review-pre-pr                   # code-review-expert 6 维审查
/commit                          # conventional commit
/open-pr feat                    # 开 feature PR

# docs 会话
/update-specs                    # 同步 PRD + ARCH
/update-docs                     # 同步 README + CHANGELOG + CONTRIBUTING
/review-pre-pr                   # 轻量 review
/commit
/open-pr docs                    # 开 docs PR
```

---

## 7. 故障排查

### 7.1 feat 会话在错的 worktree（最常见坑）

**症状**：feat 会话改了代码 commit 了，但 `git log` 看不到你的 commit；或 `/open-pr feat` 报 "refusing to PR from develop"。

**原因**：`cd` 到 feat worktree 没真生效。VS Code 集成终端从 workspace 根目录启动，Claude Code 扩展也可能从 workspace 根目录起 claude，忽略你的 cd。

**排查**：feat 会话里跑：

```
pwd && git symbolic-ref --short HEAD
```

输出必须是 feat worktree 路径 + `feature/TICK-X`。如果不是：

**恢复**（commit 误落在 develop 上的情况）：

```bash
# 1. cherry-pick 误 commit 到 feat 分支
git -C /home/Administrator/DV_ACODE_GEN_PLATFORM-feat-TICK-X cherry-pick <误 commit 的 SHA>

# 2. 回退主 worktree 的 develop（destructive，但 cherry-pick 已保住 commit）
cd /home/Administrator/DV_ACODE_GEN_PLATFORM
git reset --hard origin/develop

# 3. 从一个标准独立终端（不是 VS Code 集成的）重起 feat 会话
```

**预防**：

- 优先用 **WSL 标准终端**（不是 VS Code 内的）启动 feat / docs 会话
- 或者 VS Code → File → Open Folder → 选 feat worktree → 在那个新 VS Code 窗口里起 Claude

### 7.2 `/open-pr feat` 报 gh 不在 PATH

**症状**：`ABORT: gh CLI not installed`，但你已经装了。

**原因**：claude 会话启动时 PATH 已定型，装 gh 之后没重启会话/VS Code。

**修复**：

1. 完全关闭 VS Code（含所有窗口和终端）
2. 验证 `C:\Program Files\GitHub CLI` 在 User PATH 里（见 §1.1）
3. 重开 VS Code，新终端跑 `which gh` 应输出 gh 路径
4. 起新 feat 会话，重跑 `/open-pr feat`

**应急**：实在没法重启，可以让主会话用 `"/c/Program Files/GitHub CLI/gh.exe" pr create ...` 绝对路径手开 PR。

### 7.3 `git worktree remove` 报 "is not a working tree"

**原因**：你在 WSL 里跑了 `git worktree remove ../-feat-X`，但 worktree 注册时用的是 Windows UNC 路径（`//wsl.localhost/...`），路径字符串不匹配。

**修复**：用 `git worktree list` 输出的**完整路径**：

```bash
git worktree list  # 看实际注册路径
git worktree remove "<完整路径，含引号>"
```

### 7.4 `git branch -d` 报 "checked out at"

**原因**：worktree 还没删，分支还在被 worktree 占用。

**修复**：先 `git worktree remove`，再 `git branch -d`。

### 7.5 spec.md 看不到

**原因**：`.claude/plans/` 在 `.gitignore` 里，VS Code 资源管理器默认隐藏。

**打开方法**：

- VS Code: **Ctrl+P** → 输入 ticket id → 回车
- 或：Settings → 搜 `git.decorations` 关掉 gitignore decoration

### 7.6 spec.md 的 status 没改 accepted 就跑 worktree-init

**症状**：worktree 创建成功了，但你没意识到 spec 没正式接受。

**影响**：技术上无影响 —— worktree-init.sh 不读 status 字段。但工作流契约上 `accepted` 才是"人审通过"信号。

**修复**：手动改 status，养成习惯就行。

---

## 8. 参考资料

- [docs/spec_schema.md](spec_schema.md) — spec.md 的完整字段定义
- `.claude/agents/requirements-analyst.md` — 分析师 system prompt
- `.claude/agents/code-review-expert.md` — code reviewer system prompt
- `.claude/agents/pr-creator.md` — PR creator system prompt
- `.claude/commands/*.md` — 6 个 slash command 的执行细节
- `scripts/hooks/branch-scope-guard.py` — branch zone 拦截规则
- `scripts/worktree-init.sh` — worktree + handoff 种子模板

PR 历史：

- PR #1：Day-1 paired worktree + branch-scope hook
- PR #2：Day-2 hook 扩展 Bash 拦截
- PR #3：Day-3 4-agent scaffold + spec schema
- PR #4：smoke test ticket（TEST-1，验证整套流程）
- PR #5：Day-4 operations manual（本手册初版）
- PR #10：WORKFLOW-1 feat — 5 项 scaffold 优化（branch-scope-guard CHANGELOG 放行 + worktree-init docs-skip + /commit 自动派生 Handoff JSON + /review-pre-pr MUST/SHOULD/NIT 分诊 + /open-pr auto-merge）
- PR #11（本 PR）：WORKFLOW-1 docs — CHANGELOG 条目 + 本手册同步更新
