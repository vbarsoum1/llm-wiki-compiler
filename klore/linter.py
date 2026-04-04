"""Hybrid programmatic-scan + Director analysis lint system.

Step 1: Programmatic scans (no LLM) for structural issues.
Step 2: Director model analyzes deeper editorial issues.
Step 3: Format combined report.
Step 4: Save report, update suggestions, log results.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from klore.hash import hash_file
from klore.log import append_log, read_recent_log
from klore.models import get_client, get_model
from klore.state import CompileState

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
WIKI_SUBDIRS = ["sources", "concepts", "entities", "reports"]
PROMPTS_DIR = Path(__file__).parent / "prompts"

# Pages that are expected to have no inbound links.
INDEX_PAGES = {"index.md", "log.md", "overview.md"}


# ── Helpers ───────────────────────────────────────────────────────────


def _read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text("utf-8")


def _strip_code_fences(text: str) -> str:
    """Strip wrapping ```markdown/json ... ``` fences from LLM output."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_nl = stripped.index("\n") if "\n" in stripped else len(stripped)
        stripped = stripped[first_nl + 1 :]
    if stripped.endswith("```"):
        stripped = stripped[: -3]
    return stripped.strip()


def _all_wiki_md_files(wiki_dir: Path) -> list[Path]:
    """Collect every .md file in the wiki subdirectories and top-level."""
    files: list[Path] = []
    # Top-level .md files (index.md, log.md, overview.md, etc.)
    for md in wiki_dir.glob("*.md"):
        files.append(md)
    # Subdirectory .md files
    for subdir in WIKI_SUBDIRS:
        d = wiki_dir / subdir
        if d.is_dir():
            for md in d.rglob("*.md"):
                files.append(md)
    return sorted(set(files))


def _slug_to_possible_paths(wiki_dir: Path, slug: str) -> list[Path]:
    """Return possible file paths a [[slug]] could resolve to."""
    candidates: list[Path] = []
    for subdir in WIKI_SUBDIRS:
        candidates.append(wiki_dir / subdir / f"{slug}.md")
    # Also check top-level
    candidates.append(wiki_dir / f"{slug}.md")
    return candidates


def _slug_resolves(wiki_dir: Path, slug: str) -> bool:
    """Check if a wikilink [[slug]] resolves to an existing .md file."""
    for path in _slug_to_possible_paths(wiki_dir, slug):
        if path.is_file():
            return True
    return False


# ── Step 1: Programmatic Scan ─────────────────────────────────────────


def _programmatic_scan(wiki_dir: Path, project_dir: Path) -> dict[str, Any]:
    """Run all programmatic checks. No LLM calls — just file I/O."""
    all_files = _all_wiki_md_files(wiki_dir)
    results: dict[str, Any] = {"page_count": len(all_files)}

    # Read all file contents once
    file_contents: dict[Path, str] = {}
    for f in all_files:
        try:
            file_contents[f] = f.read_text("utf-8")
        except OSError:
            continue

    # ── 1. Broken wikilinks ──────────────────────────────────────
    broken_links: list[dict[str, str]] = []
    # outgoing links per file (slug-based key)
    outbound: dict[str, set[str]] = {}
    # inbound link counts
    inbound: dict[str, int] = {}

    # Initialize inbound counts for all known pages
    for f in all_files:
        rel = str(f.relative_to(wiki_dir))
        inbound[rel] = 0

    for f, content in file_contents.items():
        rel = str(f.relative_to(wiki_dir))
        links = WIKILINK_RE.findall(content)
        out_slugs: set[str] = set()
        for slug in links:
            slug = slug.strip()
            if not slug:
                continue
            out_slugs.add(slug)
            if _slug_resolves(wiki_dir, slug):
                # Increment inbound count for the target page
                for subdir in WIKI_SUBDIRS:
                    target = wiki_dir / subdir / f"{slug}.md"
                    target_rel = str(target.relative_to(wiki_dir))
                    if target_rel in inbound:
                        inbound[target_rel] += 1
                        break
                else:
                    # Check top-level
                    target_rel = f"{slug}.md"
                    if target_rel in inbound:
                        inbound[target_rel] += 1
            else:
                broken_links.append({"slug": slug, "file": rel})
        outbound[rel] = out_slugs

    results["broken_links"] = broken_links

    # ── 2. Orphan pages ──────────────────────────────────────────
    orphan_pages: list[str] = []
    for rel, count in sorted(inbound.items()):
        # Normalize filename for comparison
        basename = Path(rel).name.lower()
        if basename in INDEX_PAGES:
            continue
        # Skip _meta files and INDEX files
        if rel.startswith("_meta/") or Path(rel).name == "INDEX.md":
            continue
        if count == 0:
            orphan_pages.append(rel)
    results["orphan_pages"] = orphan_pages

    # ── 3. Outbound-less pages ───────────────────────────────────
    outbound_less: list[str] = []
    for f in all_files:
        rel = str(f.relative_to(wiki_dir))
        if rel.startswith("_meta/"):
            continue
        if not outbound.get(rel):
            outbound_less.append(rel)
    results["outbound_less"] = outbound_less

    # ── 4. Stale sources ─────────────────────────────────────────
    stale_sources: list[dict[str, str]] = []
    raw_dir = project_dir / "raw"
    if raw_dir.is_dir():
        state = CompileState.load(wiki_dir)
        for raw_file in sorted(raw_dir.rglob("*")):
            if raw_file.is_dir():
                continue
            rel_path = str(raw_file.relative_to(project_dir))
            current_hash = hash_file(raw_file)
            stored_hash = state.file_hashes.get(rel_path)
            if stored_hash is not None and current_hash != stored_hash:
                stale_sources.append({
                    "source": rel_path,
                    "reason": "raw file changed since last compile",
                })
            elif stored_hash is None:
                stale_sources.append({
                    "source": rel_path,
                    "reason": "raw file not yet compiled",
                })
    results["stale_sources"] = stale_sources

    # ── 5. Tag statistics ────────────────────────────────────────
    tag_counts: dict[str, int] = {}
    sources_dir = wiki_dir / "sources"
    if sources_dir.is_dir():
        for md_file in sources_dir.glob("*.md"):
            content = file_contents.get(md_file, "")
            # Parse YAML frontmatter for tags
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    import yaml

                    fm = yaml.safe_load(parts[1]) or {}
                    for tag in fm.get("tags", []) or []:
                        tag_str = str(tag).strip()
                        tag_counts[tag_str] = tag_counts.get(tag_str, 0) + 1
                except Exception:
                    pass

    rare_tags = [tag for tag, count in sorted(tag_counts.items()) if count == 1]
    results["tag_counts"] = tag_counts
    results["rare_tags"] = rare_tags

    return results


def _format_scan_results(scan: dict[str, Any]) -> str:
    """Format programmatic scan results as readable text for the Director prompt."""
    lines: list[str] = []

    lines.append(f"Pages scanned: {scan['page_count']}")

    bl = scan["broken_links"]
    lines.append(f"\nBroken wikilinks ({len(bl)}):")
    for item in bl:
        lines.append(f"  - [[{item['slug']}]] in {item['file']}")
    if not bl:
        lines.append("  (none)")

    op = scan["orphan_pages"]
    lines.append(f"\nOrphan pages ({len(op)}):")
    for p in op:
        lines.append(f"  - {p}")
    if not op:
        lines.append("  (none)")

    ol = scan["outbound_less"]
    lines.append(f"\nPages with no outbound links ({len(ol)}):")
    for p in ol:
        lines.append(f"  - {p}")
    if not ol:
        lines.append("  (none)")

    ss = scan["stale_sources"]
    lines.append(f"\nStale sources ({len(ss)}):")
    for item in ss:
        lines.append(f"  - {item['source']} ({item['reason']})")
    if not ss:
        lines.append("  (none)")

    rt = scan["rare_tags"]
    lines.append(f"\nRare tags (used by 1 source only): {len(rt)}")
    for tag in rt:
        lines.append(f"  - {tag}")
    if not rt:
        lines.append("  (none)")

    return "\n".join(lines)


# ── Step 2: Director Analysis ─────────────────────────────────────────


def _select_spot_check_pages(wiki_dir: Path, max_pages: int = 5) -> list[Path]:
    """Select pages for the Director to spot-check.

    Prefers recently modified concept/entity pages.
    """
    candidates: list[Path] = []
    for subdir in ("concepts", "entities"):
        d = wiki_dir / subdir
        if d.is_dir():
            for md in d.glob("*.md"):
                if md.name == "INDEX.md":
                    continue
                candidates.append(md)

    # Sort by modification time, most recent first
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[:max_pages]


async def _director_analysis(
    wiki_dir: Path,
    project_dir: Path,
    scan_results_text: str,
) -> dict[str, Any]:
    """Call the Director model for editorial analysis. Returns parsed JSON."""
    # Read index
    index_path = wiki_dir / "index.md"
    if not index_path.is_file():
        # Try uppercase
        index_path = wiki_dir / "INDEX.md"
    index_content = index_path.read_text("utf-8") if index_path.is_file() else "(no index found)"

    # Read recent log
    recent_log = read_recent_log(wiki_dir, n=20)

    # Select pages to spot-check
    spot_check_pages = _select_spot_check_pages(wiki_dir)
    selected_pages_parts: list[str] = []
    for page in spot_check_pages:
        rel = str(page.relative_to(wiki_dir))
        content = page.read_text("utf-8")
        selected_pages_parts.append(f"### {rel}\n\n{content}")
    selected_pages = "\n\n---\n\n".join(selected_pages_parts) if selected_pages_parts else "(no pages selected)"

    # Build prompt
    prompt_template = _read_prompt("director_lint.md")
    system_prompt = prompt_template.replace(
        "{scan_results}", scan_results_text
    ).replace(
        "{index_content}", index_content
    ).replace(
        "{selected_pages}", selected_pages
    ).replace(
        "{recent_log}", recent_log
    )

    # Call Director
    director_model = get_model("director", project_dir)
    client = get_client(project_dir)

    click.echo(f"Running Director analysis with {director_model}...", err=True)

    response = await asyncio.to_thread(
        lambda: client.chat.completions.create(
            model=director_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Analyze the wiki health and output JSON."},
            ],
        )
    )

    raw_output = response.choices[0].message.content or ""

    # Parse JSON — handle fences and parse errors gracefully
    cleaned = _strip_code_fences(raw_output)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        click.echo(
            "  warning: could not parse Director JSON response, "
            "using empty analysis.",
            err=True,
        )
        return {
            "contradictions": [],
            "stale_claims": [],
            "missing_pages": [],
            "missing_crossrefs": [],
            "thin_pages": [],
            "knowledge_gaps": [],
            "schema_improvements": [],
            "suggested_questions": [],
            "_parse_error": True,
            "_raw_output": raw_output[:500],
        }


# ── Step 3: Format Report ─────────────────────────────────────────────


def _format_report(
    scan: dict[str, Any],
    director: dict[str, Any],
) -> str:
    """Combine scan results + Director analysis into a markdown report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []

    lines.append("# Lint Report")
    lines.append("")
    lines.append(f"*Scanned {scan['page_count']} pages on {now}*")
    lines.append("")

    # ── Structural Issues ────────────────────────────────────────
    lines.append("## Structural Issues (programmatic)")
    lines.append("")

    # Broken links
    bl = scan["broken_links"]
    lines.append(f"### Broken Links ({len(bl)})")
    if bl:
        for item in bl:
            lines.append(f"- [[{item['slug']}]] in {item['file']} — no matching page found")
    else:
        lines.append("- None found")
    lines.append("")

    # Orphan pages
    op = scan["orphan_pages"]
    lines.append(f"### Orphan Pages ({len(op)})")
    if op:
        for p in op:
            lines.append(f"- {p} — no inbound links")
    else:
        lines.append("- None found")
    lines.append("")

    # Outbound-less pages
    ol = scan["outbound_less"]
    lines.append(f"### Pages With No Outbound Links ({len(ol)})")
    if ol:
        for p in ol:
            lines.append(f"- {p}")
    else:
        lines.append("- None found")
    lines.append("")

    # Stale sources
    ss = scan["stale_sources"]
    lines.append(f"### Stale Sources ({len(ss)})")
    if ss:
        for item in ss:
            lines.append(f"- {item['source']} — {item['reason']}")
    else:
        lines.append("- None found")
    lines.append("")

    # Tag stats
    rt = scan["rare_tags"]
    lines.append(f"### Rare Tags ({len(rt)})")
    if rt:
        for tag in rt:
            lines.append(f"- `{tag}` (used by 1 source)")
    else:
        lines.append("- None found")
    lines.append("")

    # ── Editorial Issues ─────────────────────────────────────────
    lines.append("## Editorial Issues (Director analysis)")
    lines.append("")

    if director.get("_parse_error"):
        lines.append("*Director analysis could not be parsed. Raw output truncated below:*")
        lines.append("")
        lines.append(f"```\n{director.get('_raw_output', '(empty)')}\n```")
        lines.append("")
    else:
        # Contradictions
        contradictions = director.get("contradictions", [])
        lines.append(f"### Contradictions ({len(contradictions)})")
        if contradictions:
            for c in contradictions:
                lines.append(
                    f"- {c.get('page_a', '?')} says \"{c.get('claim_a', '?')}\" "
                    f"but {c.get('page_b', '?')} says \"{c.get('claim_b', '?')}\""
                )
        else:
            lines.append("- None found")
        lines.append("")

        # Stale claims
        stale_claims = director.get("stale_claims", [])
        lines.append(f"### Stale Claims ({len(stale_claims)})")
        if stale_claims:
            for sc in stale_claims:
                lines.append(
                    f"- {sc.get('page', '?')}: \"{sc.get('claim', '?')}\" "
                    f"— superseded by {sc.get('superseded_by', '?')}"
                )
        else:
            lines.append("- None found")
        lines.append("")

        # Missing pages
        missing_pages = director.get("missing_pages", [])
        lines.append(f"### Missing Pages ({len(missing_pages)})")
        if missing_pages:
            for mp in missing_pages:
                mentioned = ", ".join(mp.get("mentioned_in", []))
                lines.append(
                    f"- {mp.get('name', '?')} ({mp.get('type', '?')}) "
                    f"— mentioned in {mentioned}, should have its own page"
                )
        else:
            lines.append("- None found")
        lines.append("")

        # Missing cross-references
        missing_xrefs = director.get("missing_crossrefs", [])
        lines.append(f"### Missing Cross-References ({len(missing_xrefs)})")
        if missing_xrefs:
            for mx in missing_xrefs:
                lines.append(
                    f"- {mx.get('from_page', '?')} should link to "
                    f"{mx.get('to_page', '?')} — {mx.get('reason', '?')}"
                )
        else:
            lines.append("- None found")
        lines.append("")

        # Thin pages
        thin_pages = director.get("thin_pages", [])
        lines.append(f"### Thin Pages ({len(thin_pages)})")
        if thin_pages:
            for tp in thin_pages:
                lines.append(
                    f"- {tp.get('page', '?')}: {tp.get('issue', '?')} "
                    f"— {tp.get('suggestion', '')}"
                )
        else:
            lines.append("- None found")
        lines.append("")

        # Knowledge gaps
        knowledge_gaps = director.get("knowledge_gaps", [])
        lines.append(f"### Knowledge Gaps ({len(knowledge_gaps)})")
        if knowledge_gaps:
            for kg in knowledge_gaps:
                lines.append(
                    f"- {kg.get('question', '?')} "
                    f"— suggested source: {kg.get('suggested_source', '?')}"
                )
        else:
            lines.append("- None found")
        lines.append("")

    # ── Suggestions ──────────────────────────────────────────────
    lines.append("## Suggestions")
    lines.append("")
    suggested_questions = director.get("suggested_questions", [])
    schema_improvements = director.get("schema_improvements", [])
    if suggested_questions:
        for q in suggested_questions:
            lines.append(f"- {q}")
    if schema_improvements:
        for si in schema_improvements:
            lines.append(
                f"- Schema: {si.get('current', '?')} -> "
                f"{si.get('proposed', '?')} ({si.get('reason', '')})"
            )
    if not suggested_questions and not schema_improvements:
        lines.append("- No suggestions")
    lines.append("")

    # ── Summary ──────────────────────────────────────────────────
    structural_count = len(bl) + len(op) + len(ol) + len(ss) + len(rt)

    editorial_count = 0
    if not director.get("_parse_error"):
        editorial_count = (
            len(contradictions)
            + len(stale_claims)
            + len(missing_pages)
            + len(missing_xrefs)
            + len(thin_pages)
            + len(knowledge_gaps)
        )

    auto_fixable = 0
    if not director.get("_parse_error"):
        for mp in missing_pages:
            if mp.get("auto_fixable"):
                auto_fixable += 1
        for mx in missing_xrefs:
            if mx.get("auto_fixable"):
                auto_fixable += 1

    total = structural_count + editorial_count

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Structural issues: {structural_count}")
    lines.append(f"- Editorial issues: {editorial_count}")
    lines.append(f"- Auto-fixable: {auto_fixable}")
    lines.append(f"- Total: {total}")
    lines.append("")

    return "\n".join(lines)


# ── Step 4: Save & Log ────────────────────────────────────────────────


def _save_report(
    wiki_dir: Path,
    report: str,
    director: dict[str, Any],
    total_issues: int,
) -> None:
    """Write lint report, update suggestions, and append to log."""
    meta_dir = wiki_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    # Write lint report
    report_path = meta_dir / "lint-report.md"
    report_path.write_text(report, encoding="utf-8")
    click.echo(f"Lint report saved to {report_path}", err=True)

    # Update suggestions.md
    suggestions_lines: list[str] = ["# Suggestions & Knowledge Gaps", ""]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    suggestions_lines.append(f"*Updated {now}*")
    suggestions_lines.append("")

    if not director.get("_parse_error"):
        knowledge_gaps = director.get("knowledge_gaps", [])
        if knowledge_gaps:
            suggestions_lines.append("## Knowledge Gaps")
            suggestions_lines.append("")
            for kg in knowledge_gaps:
                suggestions_lines.append(
                    f"- {kg.get('question', '?')} "
                    f"— suggested source: {kg.get('suggested_source', '?')}"
                )
            suggestions_lines.append("")

        suggested_questions = director.get("suggested_questions", [])
        if suggested_questions:
            suggestions_lines.append("## Suggested Questions")
            suggestions_lines.append("")
            for q in suggested_questions:
                suggestions_lines.append(f"- {q}")
            suggestions_lines.append("")

        schema_improvements = director.get("schema_improvements", [])
        if schema_improvements:
            suggestions_lines.append("## Schema Improvements")
            suggestions_lines.append("")
            for si in schema_improvements:
                suggestions_lines.append(
                    f"- **Current**: {si.get('current', '?')}"
                )
                suggestions_lines.append(
                    f"  **Proposed**: {si.get('proposed', '?')}"
                )
                suggestions_lines.append(
                    f"  **Reason**: {si.get('reason', '?')}"
                )
            suggestions_lines.append("")

    suggestions_path = meta_dir / "suggestions.md"
    suggestions_path.write_text("\n".join(suggestions_lines), encoding="utf-8")

    # Append to log
    details = f"Structural: {total_issues} issues found across programmatic + editorial checks."
    append_log(wiki_dir, "lint", f"{total_issues} issues found", details)


# ── Main entry point ──────────────────────────────────────────────────


async def lint(project_dir: Path) -> str:
    """Hybrid lint: programmatic scan + Director analysis."""
    wiki_dir = project_dir / "wiki"

    if not wiki_dir.is_dir() or not any(wiki_dir.iterdir()):
        return "No compiled wiki found. Run `klore compile` first."

    # ── Step 1: Programmatic scan (fast, no LLM) ─────────────────
    click.echo("Running programmatic scan...", err=True)
    scan = _programmatic_scan(wiki_dir, project_dir)
    scan_results_text = _format_scan_results(scan)
    click.echo(
        f"Programmatic scan complete: {scan['page_count']} pages, "
        f"{len(scan['broken_links'])} broken links, "
        f"{len(scan['orphan_pages'])} orphans, "
        f"{len(scan['stale_sources'])} stale sources.",
        err=True,
    )

    # ── Step 2: Director analysis (LLM) ──────────────────────────
    director = await _director_analysis(wiki_dir, project_dir, scan_results_text)

    # ── Step 3: Format report ────────────────────────────────────
    report = _format_report(scan, director)

    # ── Step 4: Save & log ───────────────────────────────────────
    # Calculate total for the log
    structural = (
        len(scan["broken_links"])
        + len(scan["orphan_pages"])
        + len(scan["outbound_less"])
        + len(scan["stale_sources"])
        + len(scan["rare_tags"])
    )
    editorial = 0
    if not director.get("_parse_error"):
        editorial = (
            len(director.get("contradictions", []))
            + len(director.get("stale_claims", []))
            + len(director.get("missing_pages", []))
            + len(director.get("missing_crossrefs", []))
            + len(director.get("thin_pages", []))
            + len(director.get("knowledge_gaps", []))
        )
    total = structural + editorial

    _save_report(wiki_dir, report, director, total)

    return report
