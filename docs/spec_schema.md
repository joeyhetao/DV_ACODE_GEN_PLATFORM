# Ticket spec schema (`.claude/plans/<ticket>.spec.md`)

This is the contract between the four multi-agent roles introduced in Day-3:

| Role | Reads from spec | Writes to spec |
|---|---|---|
| `requirements-analyst` (subagent) | user intent + PRD/ARCH | full file |
| coder (main session, feat worktree) | §2 Acceptance, §4 Sketch | — |
| `code-review-expert` (subagent, via `/review-pre-pr`) | §2 Acceptance | — |
| documenter (`/update-specs` + `/update-docs` in docs worktree) | §6 Docs Impact, §8 Machine block | — |
| `pr-creator` (subagent, via `/open-pr`) | §2 Acceptance, §7 PR Body Template | — |

The file lives at `.claude/plans/<ticket>.spec.md` (gitignored). `scripts/worktree-init.sh` copies it into both paired worktrees so each session reads from its own working tree.

## Required structure

```markdown
---
ticket: TICK-1
title: <one-line human title>
created: 2026-05-20T12:34:56Z
analyst_version: 1
status: draft
---

# TICK-1 — <title>

## 1. Problem (user-facing)

2–4 sentences. WHY this ticket exists. No implementation talk.

## 2. Acceptance Criteria

- [ ] Behavioral checkbox 1 — testable from outside the code
- [ ] Behavioral checkbox 2

These are copied verbatim into the feature PR body's "Test plan".

## 3. Scope

### In
- bullet
### Out
- bullet (explicit "we are NOT doing X this ticket")

## 4. Implementation Sketch

Optional, 5–15 lines. Analyst's best guess at the modules touched. The coder
is NOT bound to this — it's a starting hint, not a contract.

## 5. Risks / Open Questions

- bullet (analyst flags ambiguities only the coder can resolve)

## 6. Docs Impact

Hint for the docs session. Each row tells `/update-specs` / `/update-docs`
which files to even open.

- PRD §X.Y: yes|no|maybe — what changes
- ARCHITECTURE §N: yes|no|maybe — what changes
- README: touched? which section?
- CHANGELOG: <type>(<scope>): subject hint
- CONTRIBUTING: touched? (rare)
- test-manual: touched? (add test cases for any new user-visible feature — admin UI / pipeline gates / new endpoints)
- multi-agent-workflow: touched? (workflow-type tickets only)

## 7. PR Body Template

### Summary

Draft prose. `pr-creator` refines after seeing the actual diff but won't
invent claims not present here.

### Test plan

- [ ] manual smoke covering AC §2
- [ ] unit / integration tests added at <path>

## 8. Machine block

The fenced JSON below is the machine-parseable handoff for the docs session.
`update-specs.md` and `update-docs.md` Step 0.5 extract it via regex and use
it to restrict which doc files to read.

```json
{
  "ticket": "TICK-1",
  "docs_targets": ["PRD", "ARCHITECTURE", "CHANGELOG"],
  "changelog": { "type": "feat", "scope": "engine" },
  "affected_paths": ["backend/app/services/", "backend/app/api/v1/"],
  "needs_migration": false
}
```
```

## Frontmatter fields

| Key | Type | Required | Notes |
|---|---|---|---|
| `ticket` | string | yes | Match `^[A-Za-z0-9_-]+$` (same regex as `scripts/worktree-init.sh`). Must equal the filename stem. |
| `title` | string | yes | One line, free text. |
| `created` | ISO-8601 UTC | yes | `date -u +%Y-%m-%dT%H:%M:%SZ`. |
| `analyst_version` | integer | yes | Bump when analyst prompt evolves (lets future tooling detect schema drift). |
| `status` | enum | yes | `draft` (analyst output) → `accepted` (human signed off, ready for worktree-init). worktree-init does NOT enforce status — the human-readable gate is the convention. |

## §8 Machine block fields

| Key | Type | Required | Notes |
|---|---|---|---|
| `ticket` | string | yes | Must match frontmatter `ticket`. |
| `docs_targets` | array of strings | yes | Subset of `["PRD", "ARCHITECTURE", "README", "CHANGELOG", "CONTRIBUTING", "test-manual", "multi-agent-workflow"]`. Empty array means "code-only ticket, no docs PR needed". `test-manual` must be included for any ticket that adds or changes user-visible functionality (admin UI / pipeline gates / new endpoints). `multi-agent-workflow` is for scaffold/workflow-type tickets only. |
| `changelog.type` | string | yes if `"CHANGELOG"` in `docs_targets` | Conventional-commit type: `feat` \| `fix` \| `docs` \| `chore` \| `refactor` \| `test` \| `perf` \| `ci`. |
| `changelog.scope` | string | yes if `"CHANGELOG"` in `docs_targets` | Scopes used in this repo: `engine`, `llm`, `template`, `api`, `frontend`, `db`, `deploy`, `auth`, `workflow`. |
| `affected_paths` | array of strings | yes | Repo-relative POSIX directory paths the coder is expected to touch. ARCH §7 directory-tree update uses this. Empty allowed for pure-docs tickets. |
| `needs_migration` | boolean | yes | Hints whether Alembic migration is involved. `update-specs` uses this to remind the documenter to update ARCH's migration section. |

Additional optional fields are tolerated (analysts may innovate); unknown keys MUST be ignored by consumers.

## Consumer guarantees

1. **Idempotency** — analyst is deterministic given fixed inputs; rerunning `/plan-ticket` on the same ticket overwrites the file (analyst checks `status: accepted` and refuses to overwrite an accepted spec without `--force`).
2. **Locality** — every consumer reads spec.md from its own working tree (`./.claude/plans/<ticket>.spec.md`). No cross-worktree reads of the spec.
3. **JSON validity** — the §8 block must parse with `json.loads`. `scripts/hooks/test_spec_schema.sh` exercises this against a synthetic spec on every test run.

## Handoff JSON in `.code.md` (related, separate file)

`scripts/worktree-init.sh` ALSO seeds a `## Handoff JSON` block inside `.claude/state/<ticket>.code.md` (the freeform code-session notes file). The coder fills it in before opening the feature PR; the docs session reads it via path-walk-up (`../<repo>-feat-<ticket>/.claude/state/<ticket>.code.md`) during `/update-specs` Step 0.5.

The handoff JSON has the same shape as `docs_targets` / `changelog` / `affected_paths` from spec §8 — but reflects what was *actually* changed, not what was planned. When the two diverge (e.g., coder discovered a needed CHANGELOG entry the analyst missed), the handoff wins.
