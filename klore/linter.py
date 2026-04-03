"""Wiki health checks via LLM."""

from __future__ import annotations

from pathlib import Path

import click

from klore.models import get_client, get_context_limit, get_model

SKIP_DIRS = {"_meta"}
WIKI_SUBDIRS = ["sources", "concepts", "reports"]
FALLBACK_SUBDIRS = ["concepts"]
TOP_LEVEL_FILES = ["INDEX.md", "AGENTS.md"]


def _collect_wiki_content(wiki_dir: Path, include_sources: bool = True) -> str:
    """Read all .md files from wiki/, concatenate with path headers."""
    parts: list[str] = []

    for name in TOP_LEVEL_FILES:
        p = wiki_dir / name
        if p.is_file():
            parts.append(f"## {name}\n\n{p.read_text(encoding='utf-8')}")

    dirs = WIKI_SUBDIRS if include_sources else FALLBACK_SUBDIRS
    for subdir in dirs:
        d = wiki_dir / subdir
        if not d.is_dir():
            continue
        for md_file in sorted(d.rglob("*.md")):
            rel = md_file.relative_to(wiki_dir)
            parts.append(f"## {rel}\n\n{md_file.read_text(encoding='utf-8')}")

    return "\n\n---\n\n".join(parts)


def lint(project_dir: Path) -> str:
    """Run lint checks on the wiki. Returns the lint report as markdown."""
    wiki_dir = project_dir / "wiki"

    if not wiki_dir.is_dir() or not any(wiki_dir.iterdir()):
        return "No compiled wiki found. Run `klore compile` first."

    click.echo("Loading wiki content...")
    wiki_content = _collect_wiki_content(wiki_dir, include_sources=True)

    if not wiki_content.strip():
        return "No compiled wiki found. Run `klore compile` first."

    # Token budget check
    model_id = get_model("strong", project_dir)
    context_limit = get_context_limit(model_id)
    max_tokens = int(context_limit * 0.8)

    prompt_template = (
        Path(__file__).parent / "prompts" / "lint.md"
    ).read_text(encoding="utf-8")

    agents_md = (wiki_dir / "AGENTS.md").read_text(encoding="utf-8") if (wiki_dir / "AGENTS.md").is_file() else ""

    estimated_tokens = len(wiki_content) // 4
    if estimated_tokens > max_tokens:
        click.echo("Warning: wiki too large for full scan; loading indexes and concepts only.")
        wiki_content = _collect_wiki_content(wiki_dir, include_sources=False)

    prompt = prompt_template.replace("{agents_md}", agents_md).replace("{wiki_content}", wiki_content)

    click.echo(f"Running lint with {model_id}...")
    client = get_client(project_dir)
    response = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
    )
    report = response.choices[0].message.content or ""

    # Save report
    meta_dir = wiki_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    report_path = meta_dir / "lint-report.md"
    report_path.write_text(report, encoding="utf-8")
    click.echo(f"Lint report saved to {report_path}")

    return report
