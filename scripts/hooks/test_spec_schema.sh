#!/usr/bin/env bash
# Tests for the ticket spec.md schema (see docs/spec_schema.md).
#
# Strategy: synthesize a spec file in memory (no disk write under repo root),
# then run a small Python validator that:
#   1) Splits frontmatter (`---` fenced YAML) from body
#   2) Asserts required frontmatter keys exist
#   3) Extracts the §8 ```json fenced block
#   4) Asserts the JSON parses and required keys exist
#
# If the requirements-analyst prompt drifts to emit a different shape, this
# test fails — preventing silent schema breakage.
#
# Usage: bash scripts/hooks/test_spec_schema.sh

set -u

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

PASS=0
FAIL=0

# run_spec: args: <test_name> <expected_outcome> <spec_body>
# Avoids piping into the function (which would subshell PASS/FAIL away).
# Expected outcomes:
#   OK                            - spec is valid
#   BAD_FRONTMATTER              - frontmatter missing or malformed YAML
#   MISSING_FM_KEY               - frontmatter missing a required key
#   BAD_STATUS                    - status field not in {draft, accepted}
#   MISSING_JSON                  - §8 fenced ```json block absent
#   BAD_JSON                      - §8 JSON does not parse
#   MISSING_JSON_KEY             - §8 JSON missing a required key
#   TICKET_MISMATCH              - frontmatter ticket != JSON ticket
#   CHANGELOG_MISSING_TYPE_SCOPE - CHANGELOG target but type/scope empty
VALIDATOR="scripts/hooks/_spec_schema_validator.py"

run_spec() {
  local name=$1 expected=$2 input=$3
  local got
  got=$(printf '%s' "$input" | python "$VALIDATOR" "$expected" 2>&1)
  if [[ "$got" == "OK" ]]; then
    PASS=$((PASS + 1))
    printf '  ✓ %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  ✗ %s\n' "$name"
    printf '    %s\n' "$got"
  fi
}

# Reusable spec body (parameterized; substitute $TICKET / $STATUS / $JSON_BLOCK)
make_spec() {
  local ticket=$1 status=$2 json_block=$3
  cat <<SPEC
---
ticket: $ticket
title: test ticket
created: 2026-05-20T12:00:00Z
analyst_version: 1
status: $status
---

# $ticket — test ticket

## 1. Problem (user-facing)
test.

## 2. Acceptance Criteria
- [ ] thing happens

## 3. Scope
### In
- thing
### Out
- not thing

## 4. Implementation Sketch
backend/app/foo.py

## 5. Risks / Open Questions
- none

## 6. Docs Impact
- PRD §1: no
- CHANGELOG: feat(engine)

## 7. PR Body Template
### Summary
test
### Test plan
- [ ] manual

## 8. Machine block

\`\`\`json
$json_block
\`\`\`
SPEC
}

echo "=== Schema happy path ==="
run_spec "happy path — valid draft spec" "OK" "$(make_spec "TICK-1" "draft" '{
  "ticket": "TICK-1",
  "docs_targets": ["CHANGELOG"],
  "changelog": { "type": "feat", "scope": "engine" },
  "affected_paths": ["backend/app/foo.py"],
  "needs_migration": false
}')"

run_spec "happy path — empty docs_targets allowed" "OK" "$(make_spec "TICK-2" "accepted" '{
  "ticket": "TICK-2",
  "docs_targets": [],
  "affected_paths": [],
  "needs_migration": false
}')"

echo
echo "=== Schema failure modes ==="

BAD_FM=$(cat <<'BAD'
---
ticket: TICK-3
title: x
created: 2026-05-20T12:00:00Z
status: draft
---

# body

## 8. Machine block

```json
{"ticket": "TICK-3", "docs_targets": [], "affected_paths": [], "needs_migration": false}
```
BAD
)
run_spec "missing frontmatter key (analyst_version)" "MISSING_FM_KEY" "$BAD_FM"

run_spec "invalid status value" "BAD_STATUS" "$(make_spec "TICK-4" "wip" '{
  "ticket": "TICK-4",
  "docs_targets": [],
  "affected_paths": [],
  "needs_migration": false
}')"

NO_JSON=$(cat <<'NOJSON'
---
ticket: TICK-5
title: x
created: 2026-05-20T12:00:00Z
analyst_version: 1
status: draft
---

# body

## 8. Machine block

(no fenced json here)
NOJSON
)
run_spec "missing §8 JSON block" "MISSING_JSON" "$NO_JSON"

run_spec "malformed JSON in §8" "BAD_JSON" "$(make_spec "TICK-6" "draft" '{ "ticket": "TICK-6", "docs_targets": [')"

run_spec "§8 JSON missing affected_paths" "MISSING_JSON_KEY" "$(make_spec "TICK-7" "draft" '{
  "ticket": "TICK-7",
  "docs_targets": [],
  "needs_migration": false
}')"

run_spec "frontmatter/JSON ticket mismatch" "TICKET_MISMATCH" "$(make_spec "TICK-8" "draft" '{
  "ticket": "DIFFERENT-ID",
  "docs_targets": [],
  "affected_paths": [],
  "needs_migration": false
}')"

run_spec "CHANGELOG target but no type/scope" "CHANGELOG_MISSING_TYPE_SCOPE" "$(make_spec "TICK-9" "draft" '{
  "ticket": "TICK-9",
  "docs_targets": ["CHANGELOG"],
  "changelog": { "type": "", "scope": "" },
  "affected_paths": [],
  "needs_migration": false
}')"

echo
echo "================================================"
printf "  RESULTS: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "================================================"

[[ $FAIL -eq 0 ]]
