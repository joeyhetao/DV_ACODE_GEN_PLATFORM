基于 spec.md §7 + 当前分支的 commits/diff，调起 pr-creator subagent 在 GitHub 开 PR。

用户必须通过 `$ARGUMENTS` 传 PR kind：

```
/open-pr feat                 → 用 feat PR body 模板（feature/* 或 fix/* 分支）
/open-pr docs                 → 用 docs PR body 模板（docs/* 分支）
/open-pr                      → 自动按分支前缀推断 kind
/open-pr feat --no-auto-merge → 开 PR 后不调 gh pr merge --auto（默认会调，feat 才相关）
```

`gh pr create` 已加进 `.claude/settings.json` 的 `ask` 列表 —— pr-creator subagent 生成完 title+body 之后会弹权限确认框，用户在那时看一眼再放行。

开完 PR 之后默认会再调一次 `gh pr merge --auto --squash <url>`（WORKFLOW-1 Opt-5），让通过 review + status check 的 PR 自动合并，省去手动点 Merge 的环节。失败 fails-open（只 WARN，不中断），传 `--no-auto-merge` 也能完全跳过。

---

## 第零步：参数 + 环境检查

```bash
RAW_ARGS="$ARGUMENTS"
BRANCH=$(git symbolic-ref --short HEAD)

# 拆出 --no-auto-merge flag（WORKFLOW-1 Opt-5）；剩余 token 作为 KIND。
# 用 read -ra 而非 `for tok in $RAW_ARGS`，避免未引用展开触发 glob
# （`$RAW_ARGS` 含 `*` / `?` / `[` 时 shell 会就地展开成 CWD 文件名列表）。
AUTO_MERGE="yes"
KIND=""
read -ra _OPEN_PR_ARGS <<< "$RAW_ARGS"
for tok in "${_OPEN_PR_ARGS[@]}"; do
  case "$tok" in
    --no-auto-merge) AUTO_MERGE="no" ;;
    feat|docs)       KIND="$tok" ;;
    "")              ;;  # 空 token（$RAW_ARGS 本身为空时 read -ra 仍产生 1 个空元素）
    *)               echo "WARN: ignoring unknown arg '$tok'" ;;
  esac
done

# 自动推断 kind
if [ -z "$KIND" ]; then
  case "$BRANCH" in
    feature/*|fix/*|hotfix/*) KIND="feat" ;;
    docs/*) KIND="docs" ;;
    *)
      echo "ABORT: branch '$BRANCH' is not feature/fix/docs/hotfix. Specify kind explicitly: /open-pr <feat|docs>"
      exit 1
      ;;
  esac
fi

# 校验 kind 合法
case "$KIND" in
  feat|docs) ;;
  *)
    echo "ABORT: kind must be 'feat' or 'docs' (got: $KIND)"
    exit 1
    ;;
esac

# 校验 kind 与分支不冲突
case "$BRANCH:$KIND" in
  feature/*:feat|fix/*:feat|hotfix/*:feat|docs/*:docs) ;;
  *)
    echo "ABORT: kind=$KIND conflicts with branch=$BRANCH. Pick the matching kind."
    exit 1
    ;;
esac

# gh 必须装好且已 auth
if ! command -v gh >/dev/null 2>&1; then
  echo "ABORT: gh CLI not installed. Install from https://cli.github.com/ first."
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "ABORT: gh not authenticated. Run: gh auth login"
  exit 1
fi
```

---

## 第一步：基线 sanity check

```bash
# 不能从 master/main/develop 直接开 PR
case "$BRANCH" in
  master|main|develop)
    echo "ABORT: refusing to PR from '$BRANCH'. Cut a feature/ or docs/ branch first."
    exit 1
    ;;
esac

# 工作区必须干净
if [ -n "$(git status --porcelain)" ]; then
  echo "ABORT: uncommitted changes present. Run /commit first."
  git status --short
  exit 1
fi

# 至少要有一个 commit 领先 origin/develop
git fetch origin develop --quiet
AHEAD=$(git rev-list --count origin/develop..HEAD)
if [ "$AHEAD" -lt 1 ]; then
  echo "ABORT: branch has no commits ahead of origin/develop. Nothing to PR."
  exit 1
fi

# docs 分支必须基于最新 origin/develop
if [ "$KIND" = "docs" ]; then
  if ! git merge-base --is-ancestor origin/develop HEAD; then
    echo "ABORT: docs branch is not rebased onto origin/develop."
    echo "Run: git rebase origin/develop"
    exit 1
  fi
fi
```

---

## 第二步：调起 pr-creator subagent

使用 `Agent` 工具，`subagent_type=pr-creator`，prompt：

```
Open a PR for the current branch.

Kind: <KIND>
Branch: <BRANCH>
Base: develop  (or master if branch starts with hotfix/)
Ticket: <derived from branch name>

Use the body template from your system prompt that matches kind=<KIND>. Read
.claude/plans/<ticket>.spec.md if it exists; otherwise derive subject from
the latest commit on the branch.

You are gated by settings.json — the `gh pr create` invocation will trigger
a permission prompt. The human will see your final title+body before approving.
If they deny, return PR_ABORTED.

Return ONLY one of these lines on completion:
  PR_OPENED: <url>
  PR_ABORTED: <reason>
```

`<KIND>` `<BRANCH>` 用第零步算出的值替换；`<ticket>` 是 BRANCH 去掉前缀的部分。

---

## 第三步：解析 subagent 结果

subagent 的最后一行应该是：

- `PR_OPENED: <url>` → 输出给用户：
  ```
  ✓ PR opened: <url>

  Next steps:
    - Notify reviewers on GitHub.
    - After merge, if this was the feat PR, switch to the docs worktree and
      run /update-specs and /update-docs to sync documentation.
  ```

  接着按下面 3(b) 调 auto-merge。

- `PR_ABORTED: <reason>` → 原样转发理由给用户，不安抚、不重试，跳过 3(b)。

### 3(b)：自动合并（WORKFLOW-1 Opt-5）

只在 `PR_OPENED: <url>` 路径上执行；`PR_ABORTED` 与未知格式都跳过。`$AUTO_MERGE` 由第零步解析；用户传 `--no-auto-merge` 时跳过。

```bash
if [ "$AUTO_MERGE" = "yes" ]; then
  PR_URL="<刚刚 subagent 回的 url>"
  if gh pr merge --auto --squash "$PR_URL" 2>/tmp/gh-merge-err; then
    echo "✓ auto-merge enabled: $PR_URL"
    echo "  GitHub will squash-merge once required checks + approvals are green."
  else
    rc=$?
    echo "WARN: gh pr merge --auto --squash failed (exit $rc)."
    echo "      Stderr from gh:"
    sed 's/^/        /' /tmp/gh-merge-err
    echo "      Common causes: branch protection rules without 'Require status checks',"
    echo "      auto-merge disabled on the repo, or missing admin permission."
    echo "      Open the PR on GitHub and toggle auto-merge manually if desired."
  fi
else
  echo "⊘ auto-merge skipped (--no-auto-merge)."
fi
```

`gh pr merge --auto` 已加进 `.claude/settings.json` 的 `ask` 列表（与 `gh pr create` 一致），用户在权限确认框里能再卡一次。fails-open 是设计：开 PR 本身已经成功了，让用户手动 toggle auto-merge 比中断流程更轻量。

如果 subagent 返回任何其他格式（例如开始 narrating "let me try again..."），把它的最后 20 行原样转发给用户并提示 "pr-creator returned unexpected format; check gh state manually with `gh pr list`."

---

## 不做的事

- 不要 `git push` —— `gh pr create` 自带 push 行为；提前 push 反而可能撞上权限提示。
- 不要绕过 `ask` 列表 —— 即使 subagent 已经在 sandbox 里跑也不行；`gh pr create` 是 outbound 行为，必须人 confirm。
- 不要在同一个 ticket 的同一分支上重复开 PR —— 若 `gh pr list --head <branch>` 已经返回一个 open PR，subagent 应该返回 `PR_ABORTED: PR already open at <url>`。
- 不要在 docs PR 里 cc 已 merged 的 feature PR 作者 —— GitHub 自带跨 PR 引用，让 reviewer 自己点链接。
- 不要在 auto-merge 失败时改 retry / 抛错 —— 那是 fails-open 的 WARN，PR 已经开成功了。用户传 `--no-auto-merge` 也只是跳过 3(b)，不影响开 PR 本身。
- 不要把 `--no-auto-merge` 当成"取消 PR" —— 它只关掉 auto-merge 这一步。要撤 PR 走 `gh pr close`。
