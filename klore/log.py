"""Append-only log for wiki operations.

Every ingest, query, lint, and schema change gets recorded in wiki/log.md.
Entries are parseable with grep: `grep "^## \\[" log.md | tail -5`
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def append_log(
    wiki_dir: Path,
    action: str,
    title: str,
    details: str,
    editorial_notes: str | None = None,
) -> None:
    """Append a timestamped entry to wiki/log.md.

    Args:
        wiki_dir: Path to the wiki directory.
        action: One of 'ingest', 'query', 'lint', 'schema'.
        title: Short title for the entry.
        details: 1-3 lines describing what happened.
        editorial_notes: Optional Director editorial notes.
    """
    log_path = wiki_dir / "log.md"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    lines = [f"\n## [{timestamp}] {action} | {title}"]
    lines.append(details)
    if editorial_notes:
        lines.append(f"Editorial: {editorial_notes}")
    lines.append("")  # blank line separator

    entry = "\n".join(lines)

    if log_path.exists():
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
    else:
        log_path.write_text(f"# Log\n{entry}", encoding="utf-8")


def read_recent_log(wiki_dir: Path, n: int = 20) -> str:
    """Read the last N log entries. Returns empty string if no log."""
    log_path = wiki_dir / "log.md"
    if not log_path.exists():
        return "(no log yet)"

    content = log_path.read_text("utf-8")
    # Split by entry headers and take last N
    entries = content.split("\n## [")
    if len(entries) <= 1:
        return "(no entries yet)"

    recent = entries[-n:]
    # Re-add the ## [ prefix that was split on
    return "\n## [".join(recent)
