"""Long-form article generation from a compiled wiki."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import click

from klore.asker import _frontmatter_list, _load_selected_pages, ask
from klore.git import git_add_and_commit
from klore.ingester import slugify
from klore.log import append_log
from klore.models import get_client, get_model
from klore.text import fill_prompt, strip_code_fences

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
PROMPTS_DIR = Path(__file__).parent / "prompts"
WIKI_SUBDIRS = ("sources", "concepts", "entities", "reports")


def _extract_wikilinks(markdown: str) -> list[str]:
    """Extract unique wikilink slugs from markdown in first-seen order."""
    seen: set[str] = set()
    links: list[str] = []
    for raw_slug in WIKILINK_RE.findall(markdown):
        slug = raw_slug.strip()
        if slug and slug not in seen:
            seen.add(slug)
            links.append(slug)
    return links


def _resolve_wikilink(wiki_dir: Path, slug: str) -> str | None:
    """Resolve a wikilink slug to a path relative to wiki/ without .md."""
    slug_path = Path(slug)
    if slug_path.suffix == ".md":
        direct = wiki_dir / slug_path
        if direct.is_file():
            return direct.relative_to(wiki_dir).with_suffix("").as_posix()
    elif len(slug_path.parts) > 1:
        direct = wiki_dir / f"{slug}.md"
        if direct.is_file():
            return direct.relative_to(wiki_dir).with_suffix("").as_posix()

    for subdir in WIKI_SUBDIRS:
        candidate = wiki_dir / subdir / f"{slug}.md"
        if candidate.is_file():
            return candidate.relative_to(wiki_dir).with_suffix("").as_posix()

    top_level = wiki_dir / f"{slug}.md"
    if top_level.is_file():
        return top_level.relative_to(wiki_dir).with_suffix("").as_posix()

    return None


def _resolve_referenced_pages(wiki_dir: Path, research_answer: str) -> list[str]:
    """Resolve wikilinks from the research answer to loadable wiki page paths."""
    pages: list[str] = []
    seen: set[str] = set()
    for slug in _extract_wikilinks(research_answer):
        page = _resolve_wikilink(wiki_dir, slug)
        if page and page not in seen:
            seen.add(page)
            pages.append(page)
    return pages


def _report_tags(page_paths: list[str]) -> list[str]:
    """Use referenced concept pages as report tags."""
    return sorted({
        Path(page.split("/", 1)[1]).with_suffix("").as_posix()
        for page in page_paths
        if page.startswith("concepts/") and "/" in page
    })


async def longform(project_dir: Path, topic: str) -> Path:
    """Generate and save a long-form article grounded in the compiled wiki."""
    wiki_dir = project_dir / "wiki"
    client = get_client(project_dir)

    research_answer = await ask(project_dir, topic, save=False)
    page_paths = _resolve_referenced_pages(wiki_dir, research_answer)
    if not page_paths:
        raise RuntimeError(
            "Could not identify referenced wiki pages from the research answer. "
            "Run `klore ask` first and check that the answer includes wikilinks."
        )

    referenced_pages = _load_selected_pages(wiki_dir, page_paths)

    agents_path = project_dir / ".klore" / "agents.md"
    agents_md = agents_path.read_text("utf-8") if agents_path.exists() else ""
    prompt_template = (PROMPTS_DIR / "longform.md").read_text("utf-8")
    user_prompt = fill_prompt(
        prompt_template,
        agents_md=agents_md,
        topic=topic,
        research_answer=research_answer,
        referenced_pages=referenced_pages,
    )

    strong_model = get_model("strong", project_dir)
    response = client.chat.completions.create(
        model=strong_model,
        messages=[{"role": "user", "content": user_prompt}],
    )
    article = strip_code_fences(response.choices[0].message.content or "")

    report_dir = wiki_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{slugify(topic)}-longform.md"

    frontmatter = (
        "---\n"
        f"title: {json.dumps(topic)}\n"
        f"date: {json.dumps(date.today().isoformat())}\n"
        "type: longform\n"
        + _frontmatter_list("tags", _report_tags(page_paths))
        + _frontmatter_list("related_pages", page_paths)
        + "---\n\n"
    )
    report_path.write_text(frontmatter + article, encoding="utf-8")

    details = f"Pages consulted: {', '.join(page_paths[:8])}"
    append_log(wiki_dir, "longform", topic[:60], details)

    try:
        git_add_and_commit(
            project_dir,
            f"wiki: add longform — {topic[:60]}",
        )
    except RuntimeError as exc:
        click.echo(f"  warning: git commit failed: {exc}", err=True)

    return report_path
