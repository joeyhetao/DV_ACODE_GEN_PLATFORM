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

## 第四步 (a)：把 subagent 的输出原样转给用户

subagent 返回完整 review report。原样转发给用户，**不要改写、不要总结、不要给"看起来挺好"的安抚**。如果有 critical findings（subagent 用 `🔴` / `Critical:` 标的），把这部分放在前面醒目位置。

`(a)` 与 `(b)` 是两段独立输出 —— `(a)` 必须是 subagent 的原文（不重排、不删减、不"merge similar findings"），`(b)` 是主 session 基于原文的二次分诊。两者拼在同一次回复里，但 `(a)` 在前。

## 第四步 (b)：主 session 三档分诊（WORKFLOW-1 Opt-4）

读完 `(a)` 的原文后，由**主 session 自己**（不再调用 subagent）按以下分类规则把每条 finding 归到三个档位之一，然后追加输出一段名为 `## Severity Triage` 的小节。

| 档位 | 标记 / 关键词 | 释义 |
|---|---|---|
| **MUST (阻塞合并)** | subagent 原文里带 `🔴` / `Critical:` / `Security:` / `BUG:` / `BLOCKER:` 的项 | 合并前必须修；不修就是把已知缺陷推进 develop |
| **SHOULD (强烈建议)** | `🟡` / `Warning:` / `Important:` / "should fix"/"建议修复" 等 | 改了对长期维护友好；不改 PR 仍可合，但要在 PR body 里注明保留原因 |
| **NIT (可选润色)** | 其他 finding（`🟢` / `Nit:` / "suggestion:" / 文风/命名/微优化） | 真的可选；现 PR 内不改也行 |

输出格式（严格遵守这个模板，便于人眼快速扫一遍就能决定行动）：

```markdown
---

## Severity Triage

**MUST (阻塞合并)**
- <subagent 原文里这条 finding 的一句话摘要> — <source: 文件:行号 或 "general">
- ...

**SHOULD (强烈建议)**
- ...

**NIT (可选润色)**
- ...

Next steps:
  - 修完 MUST 后再开 PR；SHOULD/NIT 视精力决定，PR body 里注明保留即可。
  - 如果改了任何 finding：rerun /review-pre-pr 跑第二轮，确认新 diff 不引入回归。
  - 若 review 全 clean（三档全空）：/commit → /open-pr <feat|docs>。
```

分诊原则：
1. **不改写 subagent 原文**：摘要在 triage 段里，但 `(a)` 区的原文保留不动 —— 用户随时可以回看完整上下文。
2. **三档可空**：若 subagent 没标 `🔴`，MUST 段就空着写 "(none)"；不要硬塞。
3. **歧义保守归类**：把握不准的 finding 就上抬一档（warning → MUST 比 critical → SHOULD 安全）。
4. **不替用户决策**：分诊只是分类 + 建议，是否修、修到什么程度，用户决定。

---

## 不做的事

- 不要自动修复 subagent 指出的问题 —— 这是 review，不是 refactor。让用户决定改不改。
- 不要把 diff 写到中间文件再让 subagent 读 —— 直接拼进 prompt。
- 不要在 `docs/*` 分支跑 full mode —— 浪费 token，且会针对 markdown 误报"安全漏洞"。
- 不要把 4(b) 的分诊外包给 subagent —— 主 session 直接做。再起一个 subagent 既慢又会重新解释原文，且会把已经原样转给用户的内容再压缩一次。
- 不要在 4(b) 改写 subagent 的措辞 —— 摘要是为了扫读，不是为了"润色"。一句话一条，源行号附上，足够。
