#!/usr/bin/env python3
"""
Spec schema validator (test helper for scripts/hooks/test_spec_schema.sh).

Reads a .spec.md from stdin, validates against docs/spec_schema.md.
Prints "OK" on success or "FAIL: <reason>" on failure.

Exit codes:
  0 — outcome matched sys.argv[1] (one of: OK, BAD_FRONTMATTER, MISSING_FM_KEY,
       BAD_STATUS, MISSING_JSON, BAD_JSON, MISSING_JSON_KEY, TICKET_MISMATCH,
       CHANGELOG_MISSING_TYPE_SCOPE)
  1 — outcome did NOT match (test failure)
"""
from __future__ import annotations

import json
import re
import sys

REQUIRED_FM_KEYS = {"ticket", "title", "created", "analyst_version", "status"}
REQUIRED_JSON_KEYS = {"ticket", "docs_targets", "affected_paths", "needs_migration"}


def fail(msg: str, expected: str) -> None:
    """Print failure and exit 1 — unless expected matches, then exit 0."""
    # Caller checks msg-prefix-derived outcome against expected.
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    expected = sys.argv[1] if len(sys.argv) > 1 else "OK"
    content = sys.stdin.read()

    # 1. Split frontmatter from body
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if not m:
        if expected == "BAD_FRONTMATTER":
            print("OK")
            return
        fail("missing or malformed frontmatter (no leading --- block)", expected)
    fm_text, body = m.group(1), m.group(2)

    # 2. Parse frontmatter (flat key: value — schema doesn't allow nesting)
    fm: dict[str, str] = {}
    for line in fm_text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            if expected == "BAD_FRONTMATTER":
                print("OK")
                return
            fail(f"malformed frontmatter line: {line!r}", expected)
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()

    missing_fm = REQUIRED_FM_KEYS - set(fm.keys())
    if missing_fm:
        if expected == "MISSING_FM_KEY":
            print("OK")
            return
        fail(f"frontmatter missing keys: {sorted(missing_fm)}", expected)

    if fm.get("status") not in ("draft", "accepted"):
        if expected == "BAD_STATUS":
            print("OK")
            return
        fail(f"status must be draft|accepted, got: {fm.get('status')!r}", expected)

    # 3. Extract §8 JSON block
    jm = re.search(
        r"## 8\. Machine block.*?```json\s*\n(.*?)\n```",
        body,
        re.DOTALL,
    )
    if not jm:
        if expected == "MISSING_JSON":
            print("OK")
            return
        fail("§8 fenced ```json block not found", expected)

    # 4. Parse JSON
    try:
        data = json.loads(jm.group(1))
    except json.JSONDecodeError as e:
        if expected == "BAD_JSON":
            print("OK")
            return
        fail(f"§8 JSON decode error: {e}", expected)

    missing_json = REQUIRED_JSON_KEYS - set(data.keys())
    if missing_json:
        if expected == "MISSING_JSON_KEY":
            print("OK")
            return
        fail(f"§8 JSON missing keys: {sorted(missing_json)}", expected)

    # 5. Cross-check: frontmatter ticket == JSON ticket
    if fm.get("ticket") != data.get("ticket"):
        if expected == "TICKET_MISMATCH":
            print("OK")
            return
        fail(
            f"frontmatter ticket {fm.get('ticket')!r} != JSON ticket {data.get('ticket')!r}",
            expected,
        )

    # 6. If CHANGELOG in docs_targets, changelog.{type,scope} required
    if "CHANGELOG" in (data.get("docs_targets") or []):
        cl = data.get("changelog") or {}
        if not cl.get("type") or not cl.get("scope"):
            if expected == "CHANGELOG_MISSING_TYPE_SCOPE":
                print("OK")
                return
            fail(
                "docs_targets contains CHANGELOG but changelog.type or .scope is empty",
                expected,
            )

    if expected == "OK":
        print("OK")
        return
    print(f"FAIL: expected {expected} but spec validated as OK")
    sys.exit(1)


if __name__ == "__main__":
    main()
