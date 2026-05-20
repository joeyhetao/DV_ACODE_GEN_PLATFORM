#!/usr/bin/env python3
"""
PreToolUse hook: branch file-scope guard.

Enforces the multi-agent workflow contract:

  feature/*, fix/*  → may NOT modify docs (PRD/ARCHITECTURE/README/...)
  docs/*            → may NOT modify code (backend/, frontend/src/, ...)
  spec/*            → may ONLY modify .claude/plans/ and .claude/state/
                      (requirements-analyst session, optional opt-in)
  hotfix/*          → all paths allowed (audit log only)
  master/main/develop/other → allowed (admin / bootstrap)

Override: write `feature` | `docs` | `spec` | `hotfix` into
`.claude/state/<ticket>.mode` (where <ticket> is the path segment after the
branch prefix) to force a mode regardless of branch name.

Tools handled:
  Edit / Write / MultiEdit / NotebookEdit
    → check tool_input.file_path
  Bash
    → parse tool_input.command for file-writing patterns
      (`sed -i`, `tee`, output redirects `>` / `>>`)
      and git staging/committing operations
      (`git add`, `git commit`)

Limitations (intentional, see CONTRIBUTING.md §9):
  - `python -c "open('x', 'w')..."`, `awk -i inplace`, and other opaque
    write paths are not statically parsed. The `git commit` stage check
    is the catch-all: any dirty file in protected scope blocks the commit.
  - `git -C /other/repo ...` is parsed but the check still runs against
    THIS repo's git state. Acceptable since cross-repo edits from inside
    a worktree are rare.

Contract: Claude Code feeds the tool call as JSON on stdin. Exit 0 = allow,
exit 2 = block; stderr is shown to the model.
"""
from __future__ import annotations

import json
import re
import shlex
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

# spec mode (requirements-analyst session): may ONLY write into these prefixes.
# Everything else (PRD, ARCH, backend/, frontend/, docs/, root files, etc.) is blocked.
SPEC_ALLOW_REGEX = re.compile(r"^\.claude/plans/|^\.claude/state/")

NOISE_REDIRECT_TARGETS = {
    "/dev/null",
    "/dev/stderr",
    "/dev/stdout",
    "/tmp",
}


def _git(*args: str, cwd: Path | None = None) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args],
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=str(cwd) if cwd else None,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _resolve_to_repo(path: str, repo_root: Path) -> str | None:
    """Resolve `path` (absolute or relative to repo_root) to repo-relative
    POSIX. Return None if outside the repo or unresolvable."""
    try:
        p = Path(path)
        if not p.is_absolute():
            p = repo_root / p
        return p.resolve().relative_to(repo_root.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _violates(rel: str, mode: str) -> bool:
    """True if a path violates the branch's file-scope contract."""
    if mode in ("feature", "fix"):
        return bool(DOC_REGEX.search(rel))
    if mode == "docs":
        if OFFTOPIC_EXCEPTION.search(rel):
            return False
        return bool(CODE_REGEX.search(rel))
    if mode == "spec":
        return not bool(SPEC_ALLOW_REGEX.search(rel))
    return False


def _extract_write_targets(cmd: str) -> list[tuple[str, str]]:
    """Best-effort regex scan for paths that the bash command would WRITE.
    Returns [(kind, raw_path), ...]."""
    targets: list[tuple[str, str]] = []

    # sed -i[SUFFIX] [...flags / -e EXPR ...] [SCRIPT] FILE
    # The FILE is always the LAST positional arg in a sed invocation.
    # Strategy: locate `sed ... -i[SUFFIX]`, capture everything until a shell
    # separator, shlex-tokenize, and pick the last non-flag token.
    for m in re.finditer(
        r"\bsed\b[^|&<>;\n]*?\s+-i(?:\S*)?\s+(.+?)(?=[|&<>;\n]|$)",
        cmd,
    ):
        try:
            tokens = shlex.split(m.group(1))
        except ValueError:
            continue
        file_arg = None
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t in ("-e", "-E", "-f", "--expression", "--file"):
                i += 2  # flag + its argument
                continue
            if t.startswith("-"):
                i += 1
                continue
            file_arg = t
            i += 1
        if file_arg:
            targets.append(("sed -i", file_arg))

    # tee [-a|-i|-p] FILE [FILE ...]
    for m in re.finditer(
        r"\btee\b(?:\s+-[aip]+)*\s+((?:'[^']*'|\"[^\"]*\"|[^\s|&<>;-][^\s|&<>;]*))",
        cmd,
    ):
        target = m.group(1).strip("'\"")
        targets.append(("tee", target))

    # Output redirects: > path, >> path
    # Negative lookbehind excludes: 2>, 1>, &>, >&, <>, >>
    # (We DO match `>>` by allowing one optional second `>` in the operator.)
    for m in re.finditer(
        r"(?<![<>&\d])>>?\s*((?:'[^']*'|\"[^\"]*\"|[^\s|&<>;]+))",
        cmd,
    ):
        target = m.group(1).strip("'\"")
        if target in NOISE_REDIRECT_TARGETS or target.startswith("&"):
            continue
        targets.append(("redirect", target))

    return targets


def _has_all_flag(args: list[str]) -> bool:
    """True if `git commit` args include -a / --all (or bundled -am, -ma, etc.)."""
    for a in args:
        if a in ("-a", "--all"):
            return True
        if a.startswith("-") and not a.startswith("--") and len(a) > 1 and "a" in a[1:]:
            return True
    return False


def _git_add_targets(args: list[str], repo_root: Path) -> list[tuple[str, str]]:
    """Use `git add --dry-run` to learn what files `git add <args>` would stage."""
    safe_args = [a for a in args if a not in ("--dry-run", "-n")]
    try:
        out = subprocess.check_output(
            ["git", "add", "--dry-run", *safe_args],
            cwd=str(repo_root),
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError:
        return []

    targets: list[tuple[str, str]] = []
    for line in out.splitlines():
        m = re.match(r"^(?:add|remove)\s+'(.+)'\s*$", line.strip())
        if m:
            targets.append(("git add", m.group(1)))
    return targets


def _git_commit_targets(args: list[str], repo_root: Path) -> list[tuple[str, str]]:
    """For `git commit`: staged files always; if -a/--all, also dirty tracked files."""
    targets: list[tuple[str, str]] = []

    staged = _git("diff", "--cached", "--name-only", cwd=repo_root) or ""
    for f in staged.splitlines():
        if f:
            targets.append(("staged for commit", f))

    if _has_all_flag(args):
        dirty = _git("diff", "--name-only", cwd=repo_root) or ""
        for f in dirty.splitlines():
            if f:
                targets.append(("commit -a auto-stage", f))

    return targets


def _extract_git_targets(cmd: str, repo_root: Path) -> list[tuple[str, str]]:
    """Detect git add / git commit and return what they would touch."""
    try:
        parts = shlex.split(cmd.strip(), posix=True)
    except ValueError:
        return []
    if not parts or parts[0] != "git":
        return []

    # Skip global flags (-C, --git-dir, --work-tree, -c key=val, etc.)
    i = 1
    while i < len(parts):
        p = parts[i]
        if p in ("-C", "--git-dir", "--work-tree", "-c"):
            i += 2
            continue
        if p.startswith("-"):
            i += 1
            continue
        break
    if i >= len(parts):
        return []

    subcmd = parts[i]
    sub_args = parts[i + 1 :]

    if subcmd == "add":
        return _git_add_targets(sub_args, repo_root)
    if subcmd == "commit":
        return _git_commit_targets(sub_args, repo_root)
    return []


def _block(branch: str, mode: str, ticket: str, hits: list[tuple[str, str]], tool: str) -> None:
    """Emit a block message and exit 2."""
    if mode in ("feature", "fix"):
        scope = "doc"
        hint = (
            f"Resolution: switch to a docs/* worktree to edit doc files, "
            f"or write 'hotfix' into .claude/state/{ticket}.mode for an emergency."
        )
    elif mode == "docs":
        scope = "code"
        hint = "Resolution: switch to a feature/* worktree to edit code files."
    elif mode == "spec":
        scope = "anything outside .claude/plans/ or .claude/state/"
        hint = (
            "Resolution: requirements-analyst sessions may only draft spec files. "
            "Switch to a feature/* or docs/* worktree to edit code or docs."
        )
    else:
        scope = "?"
        hint = ""
    items = "\n".join(f"  - {kind}: {p}" for kind, p in hits)
    print(
        f"[branch-scope-guard] BLOCK ({tool}): branch={branch} (mode={mode}) "
        f"cannot modify {scope} files:\n{items}\n  {hint}",
        file=sys.stderr,
    )
    sys.exit(2)


def _check_path_tool(payload: dict, repo_root: Path, mode: str, branch: str, ticket: str) -> None:
    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        return
    rel = _resolve_to_repo(file_path, repo_root)
    if rel is None:
        return
    if _violates(rel, mode):
        _block(branch, mode, ticket, [("file_path", rel)], payload.get("tool_name", "Edit"))


def _check_bash_tool(payload: dict, repo_root: Path, mode: str, branch: str, ticket: str) -> None:
    cmd = (payload.get("tool_input") or {}).get("command", "")
    if not cmd:
        return

    candidates = _extract_write_targets(cmd) + _extract_git_targets(cmd, repo_root)
    hits: list[tuple[str, str]] = []
    for kind, raw in candidates:
        rel = _resolve_to_repo(raw, repo_root)
        if rel is None:
            continue
        if _violates(rel, mode):
            hits.append((kind, rel))

    if hits:
        _block(branch, mode, ticket, hits, "Bash")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    repo_root_str = _git("rev-parse", "--show-toplevel")
    if not repo_root_str:
        sys.exit(0)
    repo_root = Path(repo_root_str)

    branch = _git("symbolic-ref", "--short", "HEAD")
    if not branch:
        sys.exit(0)

    ticket = branch.split("/", 1)[1] if "/" in branch else ""

    mode: str | None = None
    if ticket:
        mode_file = repo_root / ".claude" / "state" / f"{ticket}.mode"
        if mode_file.exists():
            mode = mode_file.read_text(encoding="utf-8").strip().lower() or None

    if not mode:
        if branch.startswith(("feature/", "fix/")):
            mode = "feature"
        elif branch.startswith("docs/"):
            mode = "docs"
        elif branch.startswith("spec/"):
            mode = "spec"
        elif branch.startswith("hotfix/"):
            mode = "hotfix"
        else:
            sys.exit(0)

    if mode == "hotfix":
        tool_name = payload.get("tool_name", "?")
        ti = payload.get("tool_input") or {}
        what = ti.get("file_path") or ti.get("command", "?")
        if isinstance(what, str) and len(what) > 80:
            what = what[:77] + "..."
        print(
            f"[branch-scope-guard] hotfix mode: allowing {tool_name} {what} on {branch}",
            file=sys.stderr,
        )
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    if tool_name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        _check_path_tool(payload, repo_root, mode, branch, ticket)
    elif tool_name == "Bash":
        _check_bash_tool(payload, repo_root, mode, branch, ticket)

    sys.exit(0)


if __name__ == "__main__":
    main()
