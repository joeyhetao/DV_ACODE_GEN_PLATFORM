将用户的自然语言意图转写为结构化 spec，落到 `.claude/plans/<ticket>.spec.md`。

用户必须通过 `$ARGUMENTS` 传入 ticket id 和意图，格式：

```
/plan-ticket TICK-42 把 generate 接口的 422 错误细节改成包含 redirect_to 字段
```

第一个 token 是 ticket id（匹配 `^[A-Za-z0-9_-]+$`），剩下全部是意图正文。若 `$ARGUMENTS` 为空或第一个 token 不合法，立即终止并打印用法。

---

## 第零步：参数校验

```bash
ARGS="$ARGUMENTS"
if [ -z "$ARGS" ]; then
  echo "Usage: /plan-ticket <ticket-id> <intent>"
  echo "Example: /plan-ticket TICK-42 add WebSocket push to job status"
  exit 1
fi
TICKET=$(echo "$ARGS" | awk '{print $1}')
INTENT=$(echo "$ARGS" | cut -d' ' -f2-)
if ! [[ "$TICKET" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Error: ticket id must match ^[A-Za-z0-9_-]+$ (got: $TICKET)"
  exit 1
fi
if [ -z "$INTENT" ] || [ "$INTENT" = "$TICKET" ]; then
  echo "Error: missing intent. Usage: /plan-ticket <ticket-id> <intent>"
  exit 1
fi
```

---

## 第一步：拒绝覆盖已 accepted 的 spec

```bash
SPEC_PATH=".claude/plans/$TICKET.spec.md"
if [ -f "$SPEC_PATH" ]; then
  if grep -qE "^status:\s*accepted" "$SPEC_PATH"; then
    echo "ABORT: $SPEC_PATH already exists with status: accepted."
    echo "Pick a new ticket id, or manually flip status back to draft and rerun."
    exit 1
  fi
  echo "WARN: overwriting existing draft at $SPEC_PATH"
fi
```

---

## 第二步：确保 .claude/plans/ 存在

```bash
mkdir -p .claude/plans
```

---

## 第三步：调用 requirements-analyst subagent

使用 `Agent` 工具，`subagent_type=requirements-analyst`，prompt 内容如下（严格按此模板，不要加 greeting）：

```
Ticket id: <TICKET>
Intent: <INTENT>
Target spec path: <repo_root>/.claude/plans/<TICKET>.spec.md
Schema reference: docs/spec_schema.md (read this first).
Project context: this is the DV_ACODE_GEN_PLATFORM IC verification code-gen repo;
PRD.md and ARCHITECTURE.md are the source of truth for what already exists.

Write the spec file per the schema with status: draft. Do not modify any other
file. Return ONLY the line "SPEC_WRITTEN: <absolute path>" on success.
```

把 `<TICKET>` 和 `<INTENT>` 替换为上面解析出的值；`<repo_root>` 用 `git rev-parse --show-toplevel` 取。

---

## 第四步：解析 subagent 返回，给用户下一步指引

subagent 的最后一行应该是 `SPEC_WRITTEN: <abs_path>`。提取这个路径，然后输出：

```
✓ Draft spec written: .claude/plans/<TICKET>.spec.md

Next steps:
  1. Review the draft — pay attention to §2 Acceptance Criteria and §6 Docs Impact.
  2. If satisfied, edit frontmatter `status: draft` → `status: accepted`.
  3. Run: scripts/worktree-init.sh <TICKET>
     to cut paired feature/<TICKET> + docs/<TICKET> worktrees with the spec
     copied into both.

Schema reference: docs/spec_schema.md
```

若 subagent 没有返回 `SPEC_WRITTEN:` 行（例如它在 §5 列出 blocking 问题后停下），原样转发它的输出给用户，不要伪造路径。

---

## 不做的事

- 不要自动 commit spec 文件（spec 在 `.claude/plans/` 下，已 gitignored）。
- 不要自动跑 `scripts/worktree-init.sh` —— 等人审 spec 并改 status 后再手动跑。
- 不要在主 session 直接读 PRD.md / ARCHITECTURE.md —— 这是 subagent 的活，主 session 读了会污染上下文窗口。
