"""Git operations via subprocess — no GitPython dependency."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_TIME_UNITS = {"d": "days", "w": "weeks", "m": "months", "y": "years"}


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r


def _parse_since(spec: str) -> str:
    m = re.fullmatch(r"(\d+)([dwmy])", spec)
    if not m:
        raise ValueError(f"Invalid time spec {spec!r}. Expected e.g. '2w', '7d', '1m'.")
    return f"{m.group(1)} {_TIME_UNITS[m.group(2)]} ago"


def git_init(project_dir: Path) -> None:
    """Initialize a git repo. No-op if .git/ already exists."""
    if (project_dir / ".git").exists():
        return
    _run(["git", "init"], cwd=project_dir)


def git_add_and_commit(
    project_dir: Path, message: str, paths: list[str] | None = None,
) -> None:
    """Stage files and commit. No-op if nothing to commit."""
    _run(["git", "add", *(paths if paths is not None else ["wiki/"])], cwd=project_dir)
    status = _run(["git", "status", "--porcelain"], cwd=project_dir)
    if not status.stdout.strip():
        return
    _run(["git", "commit", "-m", message], cwd=project_dir)


def git_diff(project_dir: Path, since: str | None = None) -> str:
    """Return diff of wiki/ since last commit, or since a time spec."""
    if since is None:
        return _run(["git", "diff", "HEAD", "--", "wiki/"], cwd=project_dir).stdout
    log = _run(
        ["git", "log", f"--since={_parse_since(since)}", "--format=%H", "--reverse"],
        cwd=project_dir,
    ).stdout.strip()
    commits = log.splitlines()
    if not commits:
        return ""
    base = f"{commits[0]}~1"
    r = subprocess.run(["git", "diff", base, "HEAD", "--", "wiki/"],
                        capture_output=True, text=True, cwd=project_dir)
    # If base~1 doesn't exist (first commit), diff from that commit instead
    if r.returncode != 0:
        return _run(["git", "diff", commits[0], "HEAD", "--", "wiki/"], cwd=project_dir).stdout
    return r.stdout
