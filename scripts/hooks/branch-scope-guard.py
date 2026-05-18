#!/usr/bin/env python3
"""
PreToolUse hook: branch file-scope guard.

Enforces the multi-agent workflow contract (see plan
`.claude/plans/session-debug-claude-session-doc-prd-co-typed-dusk.md`):

  feature/*, fix/*  → may NOT edit docs (PRD/ARCHITECTURE/README/...)
  docs/*            → may NOT edit code (backend/, frontend/src/, migrations/, ...)
  hotfix/*          → all paths allowed (audit log only)
  master/main/develop/other → allowed (admin / bootstrap)

Override: write `feature` | `docs` | `hotfix` into
`.claude/state/<ticket>.mode` (where <ticket> is the path segment after the
branch prefix) to force a mode regardless of branch name.

Contract: Claude Code feeds the tool call as JSON on stdin. Exit 0 = allow,
exit 2 = block; stderr is shown to the model.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

DOC_REGEX = re.compile(
    r"^(PRD|ARCHITECTURE|README|CHANGELOG|CONTRIBUTING|CLAUDE)\.md$|^docs/"
)
CODE_REGEX = re.compile(
    r"^backend/|^frontend/src/|^migrations/|^backend/data/code_types/.*\.yaml$"
)
OFFTOPIC_EXCEPTION = re.compile(r"^backend/tests/data/offtopic_corpus\.yaml$")


def _git(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        sys.exit(0)

    repo_root = _git("rev-parse", "--show-toplevel")
    if not repo_root:
        sys.exit(0)

    try:
        rel = (
            Path(file_path).resolve().relative_to(Path(repo_root).resolve())
        ).as_posix()
    except ValueError:
        sys.exit(0)

    branch = _git("symbolic-ref", "--short", "HEAD")
    if not branch:
        sys.exit(0)

    ticket = branch.split("/", 1)[1] if "/" in branch else ""

    mode: str | None = None
    if ticket:
        mode_file = Path(repo_root) / ".claude" / "state" / f"{ticket}.mode"
        if mode_file.exists():
            mode = mode_file.read_text(encoding="utf-8").strip().lower() or None

    if not mode:
        if branch.startswith(("feature/", "fix/")):
            mode = "feature"
        elif branch.startswith("docs/"):
            mode = "docs"
        elif branch.startswith("hotfix/"):
            mode = "hotfix"
        else:
            sys.exit(0)

    if mode == "hotfix":
        print(
            f"[branch-scope-guard] hotfix mode: allowing {rel} on {branch}",
            file=sys.stderr,
        )
        sys.exit(0)

    if mode in ("feature", "fix") and DOC_REGEX.search(rel):
        print(
            f"[branch-scope-guard] BLOCK: branch={branch} (mode={mode}) "
            f"cannot edit doc file: {rel}\n"
            f"  Doc files (PRD/ARCHITECTURE/README/CHANGELOG/CONTRIBUTING/CLAUDE) "
            f"belong to docs/* branches.\n"
            f"  Resolution: switch to a docs worktree, or write 'hotfix' into "
            f".claude/state/{ticket}.mode if this is an emergency.",
            file=sys.stderr,
        )
        sys.exit(2)

    if mode == "docs":
        if OFFTOPIC_EXCEPTION.search(rel):
            sys.exit(0)
        if CODE_REGEX.search(rel):
            print(
                f"[branch-scope-guard] BLOCK: branch={branch} (mode={mode}) "
                f"cannot edit code file: {rel}\n"
                f"  Code files (backend/, frontend/src/, migrations/, "
                f"backend/data/code_types/) belong to feature/* branches.\n"
                f"  Resolution: switch to a feature worktree.",
                file=sys.stderr,
            )
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
