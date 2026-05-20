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

cat > "$repo_root/.claude/state/$ticket.code.md" <<EOF
# Code session notes — $ticket

Created: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Branch:   $feat_br
Worktree: $feat_dir

## Spec / ticket link


## Design plan
<!-- Designer subagent writes path to .claude/plans/$ticket.md here -->

## Decisions log
<!-- Coordinator appends short bullets as impl progresses -->

## Notes for Doc agent
<!-- Code session populates this BEFORE feature PR is merged.
     Format: bulleted list of "what changed in code that docs need to track".
     Example:
       - PRD §3.x: redirect_to field added to under_specified error detail
       - ARCHITECTURE §5: POST /intent-builder/chat endpoint registered
       - CHANGELOG: feat(engine): RAG-grounded intent builder
-->
EOF

cat > "$repo_root/.claude/state/$ticket.docs.md" <<EOF
# Docs session notes — $ticket

Created: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Branch:   $docs_br
Worktree: $docs_dir

## Read from .code.md
<!-- Docs session paraphrases the handoff hints here, then plans which
     PRD/ARCHITECTURE/README/CHANGELOG/CONTRIBUTING sections to touch. -->

## Open questions for Code session
<!-- If docs reveal an ambiguity in code, log it here. The user reads this
     when switching back to Code session in a later iteration. -->
EOF

echo
echo "[worktree-init] done."
echo "  Code session:  cd \"$feat_dir\" && claude"
echo "  Docs session:  cd \"$docs_dir\" && claude"
echo
echo "  State files (gitignored):"
echo "    $repo_root/.claude/state/$ticket.code.md"
echo "    $repo_root/.claude/state/$ticket.docs.md"
echo
echo "  Merge order: feature/$ticket → develop FIRST, then rebase docs/$ticket"
echo "               onto origin/develop, run /update-specs and /update-docs,"
echo "               then docs/$ticket → develop."
