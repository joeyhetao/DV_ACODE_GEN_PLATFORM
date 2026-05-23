#!/usr/bin/env bash
# Create paired worktrees for the multi-agent workflow:
#   <repo>-feat-<ticket>  on feature/<ticket>  (cut from origin/develop)
#   <repo>-docs-<ticket>  on docs/<ticket>     (cut from origin/develop)
#
# Usage:  scripts/worktree-init.sh <ticket-id> [--add-docs]
# Example: scripts/worktree-init.sh ABC-123
#          scripts/worktree-init.sh ABC-123 --add-docs   # docs worktree only,
#                                                       # for tickets whose
#                                                       # scope expanded into
#                                                       # PRD/ARCH after feat
#                                                       # worktree was made.
#
# Seeds .claude/state/<ticket>.code.md and <ticket>.docs.md as async handoff
# files. State directory is gitignored.
#
# WORKFLOW-1 Opt-2: if spec §8's docs_targets is [], the docs worktree is
# skipped automatically (no second worktree for code-only tickets). Re-run
# with --add-docs to materialize it later.
#
# Refuses to clobber existing branches or directories.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <ticket-id> [--add-docs]" >&2
  echo "Example: $0 ABC-123" >&2
  exit 1
fi

ticket="$1"
add_docs_only="no"
if [[ $# -ge 2 ]]; then
  if [[ "$2" == "--add-docs" ]]; then
    add_docs_only="yes"
  else
    echo "Error: unknown second arg '$2' (only --add-docs is supported)." >&2
    exit 1
  fi
fi

if ! [[ "$ticket" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Error: ticket id must match ^[A-Za-z0-9_-]+$" >&2
  exit 1
fi

repo_root=$(git rev-parse --show-toplevel)
parent=$(dirname "$repo_root")
repo_name=$(basename "$repo_root")

# --- WORKFLOW-1 Opt-2: parse spec §8 docs_targets ---
# `docs_targets=[]` → no doc changes planned → skip docs worktree creation.
# Absent spec or unparseable §8 → fall back to current behavior (create both),
# matching the pre-Opt-2 default. The user can still re-run with --add-docs
# later.
spec_src="$repo_root/.claude/plans/$ticket.spec.md"
skip_docs="no"
docs_targets_repr="(unknown)"
if [[ -f "$spec_src" ]]; then
  docs_targets_repr=$(python3 - "$spec_src" <<'PY'
import json, re, sys
text = open(sys.argv[1], encoding="utf-8").read()
# Last ```json fenced block in the file is §8 (machine block).
blocks = re.findall(r"```json\s*(.*?)```", text, re.DOTALL)
if not blocks:
    print("(no-json-block)")
    sys.exit(0)
try:
    obj = json.loads(blocks[-1])
except Exception as e:
    print(f"(parse-error: {e})")
    sys.exit(0)
dt = obj.get("docs_targets", "(missing)")
print(json.dumps(dt, ensure_ascii=False) if dt != "(missing)" else "(missing)")
PY
  )
  if [[ "$docs_targets_repr" == "[]" ]]; then
    skip_docs="yes"
  fi
fi

# Seed value for the Handoff JSON's docs_targets field. Use the parsed value
# verbatim when it looks like a JSON array; fall back to [] for any error tag.
if [[ "$docs_targets_repr" =~ ^\[.*\]$ ]]; then
  docs_targets_seed="$docs_targets_repr"
else
  docs_targets_seed="[]"
fi

if [[ "$add_docs_only" == "yes" ]]; then
  # User explicitly asked for the docs worktree — override any skip decision.
  skip_docs="no"
fi

feat_dir="$parent/${repo_name}-feat-$ticket"
docs_dir="$parent/${repo_name}-docs-$ticket"
feat_br="feature/$ticket"
docs_br="docs/$ticket"

echo "[worktree-init] fetching origin..."
git fetch origin --quiet

if ! git show-ref --verify --quiet refs/remotes/origin/develop; then
  echo "Error: origin/develop does not exist. Create it first:" >&2
  echo "  git push origin develop:develop" >&2
  exit 1
fi

# Branch existence checks — only check what we plan to create.
branches_to_check=()
if [[ "$add_docs_only" != "yes" ]]; then
  branches_to_check+=("$feat_br")
fi
if [[ "$skip_docs" != "yes" ]]; then
  branches_to_check+=("$docs_br")
fi
for br in "${branches_to_check[@]}"; do
  if git show-ref --verify --quiet "refs/heads/$br" \
    || git show-ref --verify --quiet "refs/remotes/origin/$br"; then
    echo "Error: branch '$br' already exists (local or remote)." >&2
    echo "Pick a different ticket id, or delete the existing branch first." >&2
    exit 1
  fi
done

# Directory existence checks — only check what we plan to create.
dirs_to_check=()
if [[ "$add_docs_only" != "yes" ]]; then
  dirs_to_check+=("$feat_dir")
fi
if [[ "$skip_docs" != "yes" ]]; then
  dirs_to_check+=("$docs_dir")
fi
for d in "${dirs_to_check[@]}"; do
  if [[ -e "$d" ]]; then
    echo "Error: directory '$d' already exists." >&2
    exit 1
  fi
done

if [[ "$add_docs_only" != "yes" ]]; then
  echo "[worktree-init] creating feature worktree: $feat_dir"
  git worktree add -b "$feat_br" "$feat_dir" origin/develop
else
  echo "[worktree-init] --add-docs mode: skipping feature worktree (assumed to exist)."
fi

if [[ "$skip_docs" != "yes" ]]; then
  echo "[worktree-init] creating docs worktree: $docs_dir"
  git worktree add -b "$docs_br" "$docs_dir" origin/develop
else
  echo "[worktree-init] docs_targets=[] in spec §8 — skipping docs worktree."
  echo "                Re-run with: $0 $ticket --add-docs"
  echo "                if ticket scope expands into PRD/ARCH/CONTRIBUTING/docs/ later."
fi

mkdir -p "$repo_root/.claude/state"

# Copy spec.md into the worktrees we created. Source: $repo_root/.claude/plans/.
# Each worktree reads from its own .claude/plans/ — keep the paths uniform.
spec_copied="no"
if [[ -f "$spec_src" ]]; then
  if [[ "$add_docs_only" != "yes" ]]; then
    mkdir -p "$feat_dir/.claude/plans"
    cp "$spec_src" "$feat_dir/.claude/plans/$ticket.spec.md"
  fi
  if [[ "$skip_docs" != "yes" ]]; then
    mkdir -p "$docs_dir/.claude/plans"
    cp "$spec_src" "$docs_dir/.claude/plans/$ticket.spec.md"
  fi
  spec_copied="yes"
else
  echo "[worktree-init] WARN: $spec_src does not exist."
  echo "                     Run /plan-ticket $ticket first, or proceed without a spec"
  echo "                     (coder + docs sessions will fall back to git-log inference)."
fi

# State files: skip code.md when --add-docs (don't clobber existing progress);
# skip docs.md when docs worktree itself was skipped.
if [[ "$add_docs_only" != "yes" ]]; then
cat > "$repo_root/.claude/state/$ticket.code.md" <<EOF
# Code session notes — $ticket

Created: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Branch:   $feat_br
Worktree: $feat_dir
Spec copied: $spec_copied

## Spec

See \`.claude/plans/$ticket.spec.md\` (copied at worktree init).
Do NOT duplicate spec content here — reference section anchors (e.g., §2, §6).

## Decisions log
<!-- Coordinator appends short bullets as impl progresses. Each bullet:
     date — decision — why. Keeps a paper trail for the docs session and
     for the PR body's "Out of scope" reasoning. -->

## Handoff JSON

The docs session reads this block via \`/update-specs\` Step 0.5. Fill it
in BEFORE running \`/open-pr feat\`. Reflects what actually changed in code
(may differ from spec §8 if scope shifted during implementation).

\`\`\`json
{
  "ticket": "$ticket",
  "docs_targets": ${docs_targets_seed:-[]},
  "changelog": { "type": "", "scope": "" },
  "affected_paths": [],
  "needs_migration": false
}
\`\`\`

## Open questions for Docs session
<!-- Things the coder couldn't decide that should be reflected in docs.
     The docs session reads this via path-walk-up from the docs worktree. -->
EOF
fi  # end add_docs_only != yes (code.md heredoc)

if [[ "$skip_docs" != "yes" ]]; then
cat > "$repo_root/.claude/state/$ticket.docs.md" <<EOF
# Docs session notes — $ticket

Created: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Branch:   $docs_br
Worktree: $docs_dir
Spec copied: $spec_copied

## Spec

See \`.claude/plans/$ticket.spec.md\` (copied at worktree init).
§6 Docs Impact is your read scope checklist.

## Cross-worktree handoff source

The code session's filled-in Handoff JSON lives at:
\`../$repo_name-feat-$ticket/.claude/state/$ticket.code.md\`

\`/update-specs\` Step 0.5 reads it automatically via path-walk-up.
Read it manually first if you want to sanity-check before running the skill.

## Open questions for Code session
<!-- If docs reveal an ambiguity in code, log it here. The user reads this
     when switching back to Code session in a later iteration. -->
EOF
fi  # end skip_docs != yes (docs.md heredoc)

echo
echo "[worktree-init] done."
if [[ "$add_docs_only" != "yes" ]]; then
  echo "  Code session:  cd \"$feat_dir\" && claude"
fi
if [[ "$skip_docs" != "yes" ]]; then
  echo "  Docs session:  cd \"$docs_dir\" && claude  (after feature PR merges)"
else
  echo "  Docs session:  (none — re-run with --add-docs if scope expands)"
fi
echo
echo "  State files (gitignored):"
if [[ "$add_docs_only" != "yes" ]]; then
  echo "    $repo_root/.claude/state/$ticket.code.md"
fi
if [[ "$skip_docs" != "yes" ]]; then
  echo "    $repo_root/.claude/state/$ticket.docs.md"
fi
if [[ "$spec_copied" == "yes" ]]; then
  if [[ "$add_docs_only" != "yes" ]]; then
    echo "    $feat_dir/.claude/plans/$ticket.spec.md  (copy)"
  fi
  if [[ "$skip_docs" != "yes" ]]; then
    echo "    $docs_dir/.claude/plans/$ticket.spec.md  (copy)"
  fi
fi
echo
if [[ "$skip_docs" == "yes" && "$add_docs_only" != "yes" ]]; then
  echo "  Notice: docs worktree skipped because spec §8 docs_targets=[]."
  echo "          $0 $ticket --add-docs  later if you need it."
  echo
fi
echo "  Workflow:"
if [[ "$skip_docs" == "yes" && "$add_docs_only" != "yes" ]]; then
  echo "    1. (in feat worktree) implement, then /review-pre-pr → /commit → /open-pr feat"
  echo "    2. Merge feature PR to develop on GitHub  (no docs step — docs_targets=[])"
else
  echo "    1. (in feat worktree) implement, then /review-pre-pr → /commit → /open-pr feat"
  echo "    2. Merge feature PR to develop on GitHub"
  echo "    3. (in docs worktree) git fetch && git rebase origin/develop"
  echo "    4. /update-specs → /update-docs → /review-pre-pr → /commit → /open-pr docs"
  echo "    5. Merge docs PR to develop"
fi
