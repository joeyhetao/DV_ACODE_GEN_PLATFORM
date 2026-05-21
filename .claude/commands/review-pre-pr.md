在开 PR 之前对当前分支的未提交 + 已 stage 改动跑一次 code-review-expert。`feature/*` 跑完整 6 维审核，`docs/*` 跑轻量风格 + 死链检查。

用户可通过 `$ARGUMENTS` 传入聚焦提示，例如：
`/review-pre-pr 重点看 RAG 改动` → 把这句话拼到 subagent 的 prompt 里
`/review-pre-pr` → 默认完整审核

---

## 第零步：判定 review mode

```bash
BRANCH=$(git symbolic-ref --short HEAD)
case "$BRANCH" in
  feature/*|fix/*) MODE="full" ;;
  docs/*) MODE="light" ;;
  hotfix/*) MODE="full" ;;
  *)
    echo "WARN: branch '$BRANCH' is not feature/fix/docs/hotfix. Running full review."
    MODE="full"
    ;;
esac
```

---

## 第一步：采集 diff

```bash
git fetch origin develop --quiet 2>/dev/null || true

# Uncommitted (working tree) + staged
UNSTAGED=$(git diff --stat 2>&1)
STAGED=$(git diff --stat --cached 2>&1)

# If both empty, also show what's on the branch vs origin/develop
if [ -z "$UNSTAGED" ] && [ -z "$STAGED" ]; then
  BRANCH_DIFF=$(git diff --stat origin/develop..HEAD 2>&1)
  if [ -z "$BRANCH_DIFF" ]; then
    echo "Nothing to review — no uncommitted changes and no commits ahead of origin/develop."
    exit 0
  fi
  echo "No uncommitted changes; reviewing committed delta vs origin/develop."
  SCOPE="branch_vs_develop"
else
  SCOPE="uncommitted"
fi
```

`SCOPE=uncommitted` 时给 subagent 的 diff 是 `git diff HEAD` + `git diff --cached`；`SCOPE=branch_vs_develop` 时是 `git diff origin/develop..HEAD`。

---

## 第二步：拼 spec §2 上下文（如果有）

```bash
TICKET=$(echo "$BRANCH" | sed -E 's|^(feature|fix|docs|hotfix)/||')
SPEC_PATH=".claude/plans/$TICKET.spec.md"
if [ -f "$SPEC_PATH" ]; then
  # 提取 §2 Acceptance Criteria 段（从 "## 2." 到下一个 "## " 之前）
  AC_SECTION=$(awk '/^## 2\./{flag=1;next} /^## /{flag=0} flag' "$SPEC_PATH")
fi
```

`$AC_SECTION` 拼进 subagent prompt 让审核以接受标准为锚 —— 防"diff 写得整齐但偏题"的情况。

---

## 第三步：调起 code-review-expert subagent

使用 `Agent` 工具，`subagent_type=code-review-expert`，prompt 按 MODE 区分。

### MODE=full（feature/fix/hotfix）

```
Review the following diff against the project's code quality and security
standards. The branch is <BRANCH>; scope is <SCOPE>.

User focus hint: <$ARGUMENTS or "no specific focus">

Acceptance criteria from spec §2 (review whether the diff actually satisfies these):

<$AC_SECTION or "no spec.md found for this ticket">

Diff to review (unified format):

<paste full `git diff HEAD` + `git diff --cached` output, or
 `git diff origin/develop..HEAD` if SCOPE=branch_vs_develop>

Apply all 6 dimensions from your system prompt (correctness, security,
performance, style, maintainability, error handling). Project-specific
red flags to surface eagerly:
- LLM call in services/core/ (CLAUDE.md violation)
- temperature > 0 in any LLM call
- Jinja2 Environment without StrictUndefined
- `except ValueError` that catches a structured pipeline gate exception
- bare `except:` clauses
- New `if code_type == "..."` branches in any non-registry file
- Mock-based test that touches production-only code paths
```

### MODE=light（docs）

```
Light review of a documentation-only diff. Scope is <SCOPE> on branch <BRANCH>.

Diff:

<paste diff as above>

Check only:
1. Markdown link validity — verify each [text](path) refers to a file that
   actually exists in the repo (run `ls path` to confirm).
2. Internal section references (§3.2, etc.) — verify the section number
   actually exists in the referenced file.
3. Outdated facts — if the diff edits ARCH or PRD, cross-check against the
   actual current code paths it claims to describe (e.g., if it says
   "pipeline.py has 7 steps", grep pipeline.py and count).
4. CHANGELOG entry shape — must match conventional commit: <type>(<scope>):
   subject.

Do NOT run security/perf review on docs. Do NOT enforce style rules from
backend code review (e.g., docstring conventions) on prose markdown.
```

把 `<BRANCH>` `<SCOPE>` `<$ARGUMENTS>` `<$AC_SECTION>` 都替换成实际值；diff 用 here-string 直接喂给 subagent。

---

## 第四步：把 subagent 的输出转给用户

subagent 返回完整 review report。原样转发给用户，**不要改写、不要总结、不要给"看起来挺好"的安抚**。如果有 critical findings（subagent 用 `🔴` / `Critical:` 标的），把这部分放在前面醒目位置。

最后附一行操作建议：

```
Next steps:
  - If findings address: edit code, then rerun /review-pre-pr for a second pass.
  - If happy with the diff: /commit, then /open-pr <feat|docs>.
```

---

## 不做的事

- 不要自动修复 subagent 指出的问题 —— 这是 review，不是 refactor。让用户决定改不改。
- 不要把 diff 写到中间文件再让 subagent 读 —— 直接拼进 prompt。
- 不要在 `docs/*` 分支跑 full mode —— 浪费 token，且会针对 markdown 误报"安全漏洞"。
