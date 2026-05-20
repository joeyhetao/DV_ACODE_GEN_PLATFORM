#!/usr/bin/env bash
# Create paired worktrees for the multi-agent workflow:
#   <repo>-feat-<ticket>  on feature/<ticket>  (cut from origin/develop)
#   <repo>-docs-<ticket>  on docs/<ticket>     (cut from origin/develop)
#
# Usage:  scripts/worktree-init.sh <ticket-id>
# Example: scripts/worktree-init.sh ABC-123
#
# Seeds .claude/state/<ticket>.code.md and <ticket>.docs.md as async handoff
# files. State directory is gitignored.
#
# Refuses to clobber existing branches or directories.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <ticket-id>" >&2
  echo "Example: $0 ABC-123" >&2
  exit 1
fi

ticket="$1"
if ! [[ "$ticket" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Error: ticket id must match ^[A-Za-z0-9_-]+$" >&2
  exit 1
fi

repo_root=$(git rev-parse --show-toplevel)
parent=$(dirname "$repo_root")
repo_name=$(basename "$repo_root")

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

for br in "$feat_br" "$docs_br"; do
  if git show-ref --verify --quiet "refs/heads/$br" \
    || git show-ref --verify --quiet "refs/remotes/origin/$br"; then
    echo "Error: branch '$br' already exists (local or remote)." >&2
    echo "Pick a different ticket id, or delete the existing branch first." >&2
    exit 1
  fi
done

for d in "$feat_dir" "$docs_dir"; do
  if [[ -e "$d" ]]; then
    echo "Error: directory '$d' already exists." >&2
    exit 1
  fi
done

echo "[worktree-init] creating feature worktree: $feat_dir"
git worktree add -b "$feat_br" "$feat_dir" origin/develop

echo "[worktree-init] creating docs worktree: $docs_dir"
git worktree add -b "$docs_br" "$docs_dir" origin/develop

mkdir -p "$repo_root/.claude/state"

# Copy spec.md into both worktrees, if it exists. The source lives at
# $repo_root/.claude/plans/<ticket>.spec.md (gitignored). Each worktree
# reads from its OWN .claude/plans/ — keep the paths uniform.
spec_src="$repo_root/.claude/plans/$ticket.spec.md"
spec_copied="no"
if [[ -f "$spec_src" ]]; then
  mkdir -p "$feat_dir/.claude/plans" "$docs_dir/.claude/plans"
  cp "$spec_src" "$feat_dir/.claude/plans/$ticket.spec.md"
  cp "$spec_src" "$docs_dir/.claude/plans/$ticket.spec.md"
  spec_copied="yes"
else
  echo "[worktree-init] WARN: $spec_src does not exist."
  echo "                     Run /plan-ticket $ticket first, or proceed without a spec"
  echo "                     (coder + docs sessions will fall back to git-log inference)."
fi

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
  "docs_targets": [],
  "changelog": { "type": "", "scope": "" },
  "affected_paths": [],
  "needs_migration": false
}
\`\`\`

## Open questions for Docs session
<!-- Things the coder couldn't decide that should be reflected in docs.
     The docs session reads this via path-walk-up from the docs worktree. -->
EOF

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

echo
echo "[worktree-init] done."
echo "  Code session:  cd \"$feat_dir\" && claude"
echo "  Docs session:  cd \"$docs_dir\" && claude  (after feature PR merges)"
echo
echo "  State files (gitignored):"
echo "    $repo_root/.claude/state/$ticket.code.md"
echo "    $repo_root/.claude/state/$ticket.docs.md"
if [[ "$spec_copied" == "yes" ]]; then
  echo "    $feat_dir/.claude/plans/$ticket.spec.md  (copy)"
  echo "    $docs_dir/.claude/plans/$ticket.spec.md  (copy)"
fi
echo
echo "  Workflow:"
echo "    1. (in feat worktree) implement, then /review-pre-pr → /commit → /open-pr feat"
echo "    2. Merge feature PR to develop on GitHub"
echo "    3. (in docs worktree) git fetch && git rebase origin/develop"
echo "    4. /update-specs → /update-docs → /review-pre-pr → /commit → /open-pr docs"
echo "    5. Merge docs PR to develop"
