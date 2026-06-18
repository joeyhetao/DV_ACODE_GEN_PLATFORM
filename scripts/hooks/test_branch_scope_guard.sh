#!/usr/bin/env bash
# Tests for scripts/hooks/branch-scope-guard.py.
#
# Strategy: stub the branch mode via .claude/state/<current-ticket>.mode
# (overrides branch-prefix inference), then feed synthetic JSON payloads
# to the hook on stdin and assert exit codes.
#
# Must be run from repo root, on a branch with a non-empty <ticket> segment
# (anything matching `<prefix>/<name>` works — we use the current branch's
# trailing segment as the ticket).
#
# Usage:  bash scripts/hooks/test_branch_scope_guard.sh

set -u

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

BRANCH=$(git symbolic-ref --short HEAD)
TICKET="${BRANCH#*/}"
if [[ "$TICKET" == "$BRANCH" || -z "$TICKET" ]]; then
  echo "ERROR: must be run from a branch with a / prefix (e.g. feature/x)." >&2
  exit 1
fi

MODE_FILE=".claude/state/${TICKET}.mode"
HOOK="scripts/hooks/branch-scope-guard.py"

PASS=0
FAIL=0
TRASH=()
ARCH_BACKUP=""

cleanup() {
  rm -f "$MODE_FILE" 2>/dev/null
  rmdir .claude/state 2>/dev/null
  rmdir .claude/plans 2>/dev/null
  # Restore any tracked file we perturbed before deleting backups
  if [[ -n "$ARCH_BACKUP" && -f "$ARCH_BACKUP" ]]; then
    cp "$ARCH_BACKUP" ARCHITECTURE.md
    rm -f "$ARCH_BACKUP"
  fi
  # Unstage anything our tests may have staged
  git restore --staged . 2>/dev/null || true
  for f in "${TRASH[@]}"; do rm -f "$f" 2>/dev/null; done
  rmdir docs 2>/dev/null
}
trap cleanup EXIT

mkdir -p .claude/state

run() {
  local name=$1 mode=$2 payload=$3 expected=$4
  echo "$mode" > "$MODE_FILE"
  echo "$payload" | python "$HOOK" >/dev/null 2>&1
  local got=$?
  if [[ $got -eq $expected ]]; then
    PASS=$((PASS + 1))
    printf '  ✓ %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  ✗ %s  (expected exit=%d, got %d)\n' "$name" "$expected" "$got"
    # Re-run to surface stderr for diagnostics
    echo "    --- stderr ---"
    echo "$payload" | python "$HOOK" 2>&1 >/dev/null | sed 's/^/    /'
  fi
}

echo "=== Edit/Write tool (file_path) ==="
run "feature: Edit PRD.md → BLOCK" feature \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$ROOT/PRD.md\"}}" 2
run "feature: Edit backend/app/main.py → ALLOW" feature \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$ROOT/backend/app/main.py\"}}" 0
run "feature: Write scripts/foo.sh → ALLOW (mixed-zone)" feature \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$ROOT/scripts/foo.sh\"}}" 0
run "feature: out-of-repo path → ALLOW" feature \
  '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/x.md"}}' 0
run "feature: empty file_path → ALLOW" feature \
  '{"tool_name":"Edit","tool_input":{}}' 0
run "docs: Edit backend/app/main.py → BLOCK" docs \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$ROOT/backend/app/main.py\"}}" 2
run "docs: Edit offtopic_corpus.yaml → ALLOW (exception)" docs \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$ROOT/backend/tests/data/offtopic_corpus.yaml\"}}" 0
run "docs: Edit PRD.md → ALLOW" docs \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$ROOT/PRD.md\"}}" 0
run "hotfix: Edit PRD.md → ALLOW" hotfix \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$ROOT/PRD.md\"}}" 0

echo
echo "=== Bash tool: explicit write commands ==="
run "feature: sed -i ... PRD.md → BLOCK" feature \
  '{"tool_name":"Bash","tool_input":{"command":"sed -i s/foo/bar/g PRD.md"}}' 2
run "feature: sed -i.bak PRD.md → BLOCK" feature \
  '{"tool_name":"Bash","tool_input":{"command":"sed -i.bak -e s/x/y/ PRD.md"}}' 2
run "feature: echo > PRD.md → BLOCK" feature \
  '{"tool_name":"Bash","tool_input":{"command":"echo hello > PRD.md"}}' 2
run "feature: echo >> README.md → BLOCK" feature \
  '{"tool_name":"Bash","tool_input":{"command":"echo hello >> README.md"}}' 2
run "feature: cat <<EOF > PRD.md → BLOCK (heredoc redirect)" feature \
  '{"tool_name":"Bash","tool_input":{"command":"cat > PRD.md <<EOF\nbody\nEOF"}}' 2
run "feature: tee CHANGELOG.md → BLOCK" feature \
  '{"tool_name":"Bash","tool_input":{"command":"echo x | tee CHANGELOG.md"}}' 2
run "feature: tee -a CONTRIBUTING.md → BLOCK" feature \
  '{"tool_name":"Bash","tool_input":{"command":"echo x | tee -a CONTRIBUTING.md"}}' 2
run "feature: ls -la → ALLOW (no write)" feature \
  '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' 0
run "feature: pytest 2>&1 → ALLOW (noise redirect)" feature \
  '{"tool_name":"Bash","tool_input":{"command":"pytest tests/ 2>&1"}}' 0
run "feature: cmd > /dev/null → ALLOW (noise target)" feature \
  '{"tool_name":"Bash","tool_input":{"command":"long-cmd > /dev/null"}}' 0
run "feature: echo > backend/foo.py → ALLOW (code is OK on feature)" feature \
  '{"tool_name":"Bash","tool_input":{"command":"echo x > backend/foo.py"}}' 0

run "docs: sed -i backend/app/main.py → BLOCK" docs \
  '{"tool_name":"Bash","tool_input":{"command":"sed -i s/x/y/ backend/app/main.py"}}' 2
run "docs: echo > backend/foo.py → BLOCK" docs \
  '{"tool_name":"Bash","tool_input":{"command":"echo x > backend/foo.py"}}' 2
run "docs: echo >> offtopic_corpus.yaml → ALLOW (exception)" docs \
  '{"tool_name":"Bash","tool_input":{"command":"echo x >> backend/tests/data/offtopic_corpus.yaml"}}' 0
run "docs: tee migrations/foo.sql → BLOCK" docs \
  '{"tool_name":"Bash","tool_input":{"command":"echo x | tee migrations/foo.sql"}}' 2

run "hotfix: sed -i PRD.md → ALLOW (override)" hotfix \
  '{"tool_name":"Bash","tool_input":{"command":"sed -i s/x/y/ PRD.md"}}' 0

echo
echo "=== spec mode (requirements-analyst session) ==="
mkdir -p .claude/plans
run "spec: Edit PRD.md → BLOCK" spec \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$ROOT/PRD.md\"}}" 2
run "spec: Edit backend/app/main.py → BLOCK" spec \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$ROOT/backend/app/main.py\"}}" 2
run "spec: Write .claude/plans/TICK-1.spec.md → ALLOW" spec \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$ROOT/.claude/plans/TICK-1.spec.md\"}}" 0
run "spec: Write .claude/state/TICK-1.mode → ALLOW" spec \
  "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$ROOT/.claude/state/TICK-1.mode\"}}" 0
run "spec: Edit docs/spec_schema.md → BLOCK (also a doc)" spec \
  "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$ROOT/docs/spec_schema.md\"}}" 2
run "spec: echo > PRD.md → BLOCK (bash redirect)" spec \
  '{"tool_name":"Bash","tool_input":{"command":"echo wip > PRD.md"}}' 2
run "spec: echo > .claude/plans/foo.spec.md → ALLOW" spec \
  '{"tool_name":"Bash","tool_input":{"command":"echo wip > .claude/plans/foo.spec.md"}}' 0

echo
echo "=== Bash tool: git add ==="
# Set up: docs/ with a temp file (matches DOC_REGEX)
mkdir -p docs
TMP_DOC="docs/__bsg_test.md"
TMP_CODE="backend/__bsg_test_dirty.py"
echo "tmp" > "$TMP_DOC"
echo "tmp" > "$TMP_CODE"
TRASH+=("$TMP_DOC" "$TMP_CODE")

run "feature: git add docs/__bsg_test.md → BLOCK" feature \
  "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"git add $TMP_DOC\"}}" 2
run "feature: git add backend/__bsg_test_dirty.py → ALLOW" feature \
  "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"git add $TMP_CODE\"}}" 0
run "feature: git add nonexistent.md → ALLOW (no-op via dry-run)" feature \
  '{"tool_name":"Bash","tool_input":{"command":"git add nonexistent-file-xyz.md"}}' 0

run "docs: git add backend/__bsg_test_dirty.py → BLOCK" docs \
  "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"git add $TMP_CODE\"}}" 2
run "docs: git add docs/__bsg_test.md → ALLOW" docs \
  "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"git add $TMP_DOC\"}}" 0

echo
echo "=== Bash tool: git commit ==="
# Stage the doc file for commit-stage tests
git add "$TMP_DOC" 2>/dev/null

run "feature: git commit (PRD-like staged) → BLOCK" feature \
  '{"tool_name":"Bash","tool_input":{"command":"git commit -m wip"}}' 2
run "feature: git commit -am (no -a-only dirty) → BLOCK (staged still hits)" feature \
  '{"tool_name":"Bash","tool_input":{"command":"git commit -am wip"}}' 2

# Unstage docs file, stage code instead → feature commit should ALLOW
git restore --staged "$TMP_DOC" 2>/dev/null
git add "$TMP_CODE" 2>/dev/null

run "feature: git commit (code staged) → ALLOW" feature \
  '{"tool_name":"Bash","tool_input":{"command":"git commit -m wip"}}' 0

# But on docs branch, code staged → BLOCK
run "docs: git commit (code staged) → BLOCK" docs \
  '{"tool_name":"Bash","tool_input":{"command":"git commit -m wip"}}' 2

# Clean up staging
git restore --staged "$TMP_CODE" 2>/dev/null

# `-a` only auto-stages TRACKED dirty files (not untracked). Perturb a real
# tracked doc file (ARCHITECTURE.md) and restore from backup immediately.
ARCH_BACKUP=$(mktemp)
cp ARCHITECTURE.md "$ARCH_BACKUP"
echo "" >> ARCHITECTURE.md  # now dirty + tracked

run "feature: git commit -am (-a picks up dirty tracked doc) → BLOCK" feature \
  '{"tool_name":"Bash","tool_input":{"command":"git commit -am wip"}}' 2
run "feature: git commit -m (no -a, dirty doc not staged) → ALLOW" feature \
  '{"tool_name":"Bash","tool_input":{"command":"git commit -m wip"}}' 0

cp "$ARCH_BACKUP" ARCHITECTURE.md
rm -f "$ARCH_BACKUP"
ARCH_BACKUP=""

echo
echo "=== Bash tool: edge cases ==="
run "feature: malformed shell (unmatched quote) → ALLOW (parse fail = pass)" feature \
  '{"tool_name":"Bash","tool_input":{"command":"echo \"unclosed"}}' 0
run "feature: git -C /other add PRD.md → BLOCK (still parsed)" feature \
  "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"git -C $ROOT add PRD.md\"}}" 0
run "feature: empty command → ALLOW" feature \
  '{"tool_name":"Bash","tool_input":{"command":""}}' 0

echo
echo "================================================"
printf "  RESULTS: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "================================================"

[[ $FAIL -eq 0 ]]
