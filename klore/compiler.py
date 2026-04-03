"""Three-pass compilation engine — the heart of Klore.

Pass 1: Extract source summaries from raw files (async, concurrent, fast tier).
Tag normalization: Merge synonym tags via LLM (between Pass 1 and 2).
Pass 2: Synthesize concept articles from grouped sources (async, concurrent, strong tier).
Pass 3: Generate index files and link graph (strong tier).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import click
import yaml

from klore.git import git_add_and_commit
from klore.hash import hash_file, hash_string
from klore.ingester import IngestionError, convert_to_markdown, slugify
from klore.models import get_client, get_model
from klore.state import CompileState

# ── Paths & constants ────────────────────────────────────────────────

PROMPTS_DIR = Path(__file__).parent / "prompts"
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
SEMAPHORE_LIMIT = 5


# ── Helpers ──────────────────────────────────────────────────────────


def _read_prompt(name: str) -> str:
    """Read a prompt template from the prompts directory."""
    return (PROMPTS_DIR / name).read_text("utf-8")


def _read_agents_md(wiki_dir: Path) -> str:
    """Read the AGENTS.md schema file, returning empty string if absent."""
    agents_path = wiki_dir / "AGENTS.md"
    if agents_path.is_file():
        return agents_path.read_text("utf-8")
    return ""


def _compute_prompt_hash(agents_md: str) -> str:
    """Hash all prompt templates + AGENTS.md to detect prompt changes."""
    parts: list[str] = [agents_md]
    for p in sorted(PROMPTS_DIR.glob("*.md")):
        parts.append(p.read_text("utf-8"))
    return hash_string("\n".join(parts))


def _parse_frontmatter(markdown: str) -> dict[str, Any]:
    """Extract YAML frontmatter from a markdown string."""
    parts = markdown.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}


def _validate_source_output(text: str) -> bool:
    """Check that LLM output looks like a valid source summary."""
    return "---" in text and "## Summary" in text


def _validate_concept_output(text: str) -> bool:
    """Check that LLM output looks like a valid concept article."""
    return "---" in text


def _collect_all_tags(sources_dir: Path) -> list[str]:
    """Scan all source summaries and collect unique tags."""
    tags: set[str] = set()
    if not sources_dir.is_dir():
        return []
    for md_file in sources_dir.glob("*.md"):
        fm = _parse_frontmatter(md_file.read_text("utf-8"))
        for tag in fm.get("tags", []) or []:
            tags.add(str(tag).strip())
    return sorted(tags)


def _apply_tag_aliases(tags: list[str], aliases: dict[str, str]) -> list[str]:
    """Normalize a list of tags using the alias mapping."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        canonical = aliases.get(tag, tag)
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def _group_sources_by_tag(
    sources_dir: Path, aliases: dict[str, str]
) -> dict[str, list[Path]]:
    """Group source summary files by their normalized tags."""
    groups: dict[str, list[Path]] = {}
    if not sources_dir.is_dir():
        return groups
    for md_file in sorted(sources_dir.glob("*.md")):
        fm = _parse_frontmatter(md_file.read_text("utf-8"))
        raw_tags = fm.get("tags", []) or []
        for tag in _apply_tag_aliases(raw_tags, aliases):
            groups.setdefault(tag, []).append(md_file)
    return groups


def _build_link_graph(wiki_dir: Path) -> dict[str, list[str]]:
    """Scan all .md files in wiki/ for [[wikilinks]] and build an adjacency list."""
    graph: dict[str, list[str]] = {}
    for md_file in wiki_dir.rglob("*.md"):
        rel = str(md_file.relative_to(wiki_dir))
        links = WIKILINK_RE.findall(md_file.read_text("utf-8"))
        if links:
            graph[rel] = sorted(set(links))
    return graph


def _list_files_summary(directory: Path, prefix: str = "") -> str:
    """List markdown files in a directory as bullet points for index prompts."""
    if not directory.is_dir():
        return "(none)"
    lines: list[str] = []
    for md_file in sorted(directory.glob("*.md")):
        if md_file.name == "INDEX.md":
            continue
        slug = md_file.stem
        fm = _parse_frontmatter(md_file.read_text("utf-8"))
        title = fm.get("title", slug)
        tags = fm.get("tags", [])
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"- [[{prefix}{slug}]]: {title}{tag_str}")
    return "\n".join(lines) if lines else "(none)"


def _atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically via tmp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)


# ── LLM call wrapper ────────────────────────────────────────────────


def _llm_call_sync(
    client: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Synchronous LLM call via the OpenAI SDK."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or ""


async def _llm_call(
    client: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Async wrapper: run the synchronous OpenAI client in a thread."""
    return await asyncio.to_thread(
        _llm_call_sync, client, model, system_prompt, user_prompt
    )


# ── Pass 1: Source Extraction ────────────────────────────────────────


async def _process_source(
    file_path: Path,
    project_dir: Path,
    wiki_dir: Path,
    client: Any,
    model: str,
    agents_md: str,
    existing_tags: list[str],
    state: CompileState,
    semaphore: asyncio.Semaphore,
) -> tuple[bool, bool]:
    """Process a single source file through Pass 1.

    Returns (success, skipped).
    """
    async with semaphore:
        rel_path = str(file_path.relative_to(project_dir))
        filename = file_path.name

        # Convert to markdown
        try:
            source_content = await asyncio.to_thread(convert_to_markdown, file_path)
        except IngestionError as exc:
            click.echo(f"  warning: skipping {filename}: {exc}", err=True)
            return False, False

        # Build prompt
        prompt_template = _read_prompt("compile_source.md")
        user_prompt = prompt_template.format(
            agents_md=agents_md,
            existing_tags=", ".join(existing_tags) if existing_tags else "(none yet)",
            filename=filename,
            source_content=source_content,
        )

        # Call LLM
        output = await _llm_call(
            client, model, "You are a knowledge compiler.", user_prompt
        )

        # Validate
        if not _validate_source_output(output):
            # Retry once
            retry_msg = (
                "Your output was malformed. Please produce valid markdown "
                "starting with YAML frontmatter."
            )
            output = await _llm_call(
                client,
                model,
                "You are a knowledge compiler.",
                user_prompt + "\n\n" + retry_msg,
            )
            if not _validate_source_output(output):
                click.echo(
                    f"  warning: malformed output for {filename}, skipping",
                    err=True,
                )
                return False, False

        # Write atomically to wiki/sources/{slug}.md
        slug = slugify(file_path.stem)
        dest = wiki_dir / "sources" / f"{slug}.md"
        _atomic_write(dest, output)

        # Update state
        file_hash = await asyncio.to_thread(hash_file, file_path)
        state.update_hash(rel_path, file_hash)

        return True, False


async def _pass1(
    project_dir: Path,
    wiki_dir: Path,
    raw_dir: Path,
    client: Any,
    agents_md: str,
    state: CompileState,
    full: bool,
) -> dict[str, int]:
    """Pass 1: Extract source summaries from raw files."""
    model = get_model("fast", project_dir)

    # Determine which sources need processing
    if full:
        sources = sorted(p for p in raw_dir.rglob("*") if p.is_file())
    else:
        new, changed, _removed = state.diff_sources(raw_dir)
        sources = sorted(
            [project_dir / p for p in new + changed]
        )

    if not sources:
        click.echo("Pass 1: no sources to process.", err=True)
        return {"sources_processed": 0, "pass1_skipped": 0, "pass1_errors": 0}

    click.echo(f"Pass 1: processing {len(sources)} sources...", err=True)

    # Ensure output directory exists
    (wiki_dir / "sources").mkdir(parents=True, exist_ok=True)

    # Collect existing tags for context
    existing_tags = _collect_all_tags(wiki_dir / "sources")

    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [
        _process_source(
            src, project_dir, wiki_dir, client, model,
            agents_md, existing_tags, state, semaphore,
        )
        for src in sources
    ]
    results = await asyncio.gather(*tasks)

    processed = sum(1 for success, _ in results if success)
    errors = sum(1 for success, skipped in results if not success and not skipped)

    click.echo(
        f"Pass 1: done — {processed} processed, {errors} errors.", err=True
    )
    return {
        "sources_processed": processed,
        "pass1_skipped": len(sources) - processed - errors,
        "pass1_errors": errors,
    }


# ── Tag Normalization ────────────────────────────────────────────────


async def _normalize_tags(
    wiki_dir: Path,
    client: Any,
    model: str,
    agents_md: str,
) -> dict[str, str]:
    """Normalize tags across all source summaries via LLM."""
    all_tags = _collect_all_tags(wiki_dir / "sources")
    if not all_tags:
        click.echo("Tag normalization: no tags found, skipping.", err=True)
        return {}

    click.echo(
        f"Tag normalization: {len(all_tags)} unique tags...", err=True
    )

    prompt_template = _read_prompt("normalize_tags.md")
    user_prompt = prompt_template.format(tag_list="\n".join(f"- {t}" for t in all_tags))

    output = await _llm_call(
        client, model, "You are a tag normalizer.", user_prompt
    )

    # Parse JSON from response — strip markdown fences if present
    cleaned = output.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (```json or ```)
        cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        aliases: dict[str, str] = json.loads(cleaned)
    except json.JSONDecodeError:
        click.echo(
            "  warning: could not parse tag normalization response, "
            "using identity mapping.",
            err=True,
        )
        aliases = {t: t for t in all_tags}

    # Write to wiki/_meta/tag-aliases.json
    meta_dir = wiki_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "tag-aliases.json").write_text(
        json.dumps(aliases, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    normalized_count = sum(1 for k, v in aliases.items() if k != v)
    click.echo(
        f"Tag normalization: done — {normalized_count} tags merged.", err=True
    )
    return aliases


# ── Pass 2: Concept Synthesis ────────────────────────────────────────


async def _process_concept(
    tag: str,
    source_files: list[Path],
    wiki_dir: Path,
    client: Any,
    model: str,
    agents_md: str,
    known_concepts: list[str],
    state: CompileState,
    semaphore: asyncio.Semaphore,
) -> bool:
    """Synthesize a single concept article from grouped sources.

    Returns True on success.
    """
    async with semaphore:
        concept_slug = slugify(tag)
        concept_name = tag.replace("-", " ").title()

        # Gather source summaries
        summaries: list[str] = []
        source_slugs: list[str] = []
        for sf in source_files:
            content = sf.read_text("utf-8")
            summaries.append(f"### {sf.stem}\n\n{content}")
            source_slugs.append(sf.stem)

        source_summaries = "\n\n---\n\n".join(summaries)

        # Check for existing article
        existing_path = wiki_dir / "concepts" / f"{concept_slug}.md"
        existing_article = ""
        if existing_path.is_file():
            existing_article = existing_path.read_text("utf-8")

        # Build prompt
        prompt_template = _read_prompt("compile_concept.md")
        user_prompt = prompt_template.format(
            agents_md=agents_md,
            concept_name=concept_name,
            source_count=len(source_files),
            known_concepts=", ".join(f"[[{c}]]" for c in known_concepts)
            if known_concepts
            else "(none)",
            source_summaries=source_summaries,
            existing_article=existing_article or "(new concept)",
        )

        # Call LLM
        output = await _llm_call(
            client, model, "You are a knowledge compiler.", user_prompt
        )

        # Validate
        if not _validate_concept_output(output):
            retry_msg = (
                "Your output was malformed. Please produce valid markdown "
                "starting with YAML frontmatter."
            )
            output = await _llm_call(
                client,
                model,
                "You are a knowledge compiler.",
                user_prompt + "\n\n" + retry_msg,
            )
            if not _validate_concept_output(output):
                click.echo(
                    f"  warning: malformed output for concept {tag}, skipping",
                    err=True,
                )
                return False

        # Write atomically
        _atomic_write(existing_path, output)

        # Update state
        state.update_concept_sources(concept_slug, source_slugs)

        return True


async def _pass2(
    wiki_dir: Path,
    project_dir: Path,
    client: Any,
    agents_md: str,
    state: CompileState,
    aliases: dict[str, str],
) -> int:
    """Pass 2: Synthesize concept articles from grouped sources."""
    model = get_model("strong", project_dir)
    sources_dir = wiki_dir / "sources"

    # Group sources by normalized tags
    groups = _group_sources_by_tag(sources_dir, aliases)

    # Filter to tags with 2+ sources
    eligible = {tag: files for tag, files in groups.items() if len(files) >= 2}

    if not eligible:
        click.echo("Pass 2: no concepts with 2+ sources, skipping.", err=True)
        return 0

    click.echo(
        f"Pass 2: synthesizing {len(eligible)} concepts...", err=True
    )

    # Ensure output directory exists
    (wiki_dir / "concepts").mkdir(parents=True, exist_ok=True)

    # All concept slugs for cross-linking
    known_concepts = sorted(slugify(tag) for tag in eligible)

    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [
        _process_concept(
            tag, files, wiki_dir, client, model,
            agents_md, known_concepts, state, semaphore,
        )
        for tag, files in sorted(eligible.items())
    ]
    results = await asyncio.gather(*tasks)

    generated = sum(1 for r in results if r)
    click.echo(f"Pass 2: done — {generated} concepts generated.", err=True)
    return generated


# ── Pass 3: Index Generation ────────────────────────────────────────


async def _pass3(
    wiki_dir: Path,
    project_dir: Path,
    client: Any,
    agents_md: str,
) -> None:
    """Pass 3: Generate index files and link graph."""
    model = get_model("strong", project_dir)

    click.echo("Pass 3: generating indexes...", err=True)

    # Gather listings
    concept_list = _list_files_summary(wiki_dir / "concepts", prefix="concepts/")
    source_list = _list_files_summary(wiki_dir / "sources", prefix="sources/")

    reports_dir = wiki_dir / "reports"
    report_list = _list_files_summary(reports_dir, prefix="reports/")

    concept_count = len(list((wiki_dir / "concepts").glob("*.md"))) if (wiki_dir / "concepts").is_dir() else 0
    source_count = len(list((wiki_dir / "sources").glob("*.md"))) if (wiki_dir / "sources").is_dir() else 0
    report_count = len(list(reports_dir.glob("*.md"))) if reports_dir.is_dir() else 0

    # Exclude INDEX.md from counts
    if (wiki_dir / "concepts" / "INDEX.md").is_file():
        concept_count -= 1
    if (wiki_dir / "sources" / "INDEX.md").is_file():
        source_count -= 1
    if (reports_dir / "INDEX.md").is_file():
        report_count -= 1

    prompt_template = _read_prompt("compile_index.md")

    # Generate three index files concurrently
    index_specs = [
        ("main", wiki_dir / "INDEX.md"),
        ("concepts", wiki_dir / "concepts" / "INDEX.md"),
        ("sources", wiki_dir / "sources" / "INDEX.md"),
    ]

    async def _generate_index(index_type: str, dest: Path) -> None:
        user_prompt = prompt_template.format(
            agents_md=agents_md,
            index_type=index_type,
            concept_count=concept_count,
            concept_list=concept_list,
            source_count=source_count,
            source_list=source_list,
            report_count=report_count,
            report_list=report_list,
        )
        output = await _llm_call(
            client, model, "You are a knowledge compiler.", user_prompt
        )
        _atomic_write(dest, output)

    await asyncio.gather(*[
        _generate_index(idx_type, dest)
        for idx_type, dest in index_specs
    ])

    # Build link graph
    link_graph = _build_link_graph(wiki_dir)
    meta_dir = wiki_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "link-graph.json").write_text(
        json.dumps(link_graph, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    click.echo("Pass 3: done — indexes and link graph generated.", err=True)


# ── Main entry point ─────────────────────────────────────────────────


async def compile_wiki(project_dir: Path, full: bool = False) -> dict:
    """Run the three-pass compilation. Returns stats dict."""
    wiki_dir = project_dir / "wiki"
    raw_dir = project_dir / "raw"

    # Ensure directories exist
    wiki_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Load state and agents
    state = CompileState.load(wiki_dir)
    agents_md = _read_agents_md(wiki_dir)
    prompt_hash = _compute_prompt_hash(agents_md)

    # Check if full recompile needed due to prompt changes
    if state.needs_full_recompile(prompt_hash):
        click.echo(
            "Prompts or AGENTS.md changed — forcing full recompile.", err=True
        )
        full = True
    state.set_prompt_hash(prompt_hash)

    # Initialize client
    client = get_client(project_dir)

    # ── Pass 1 ────────────────────────────────────────────────────
    pass1_stats = await _pass1(
        project_dir, wiki_dir, raw_dir, client, agents_md, state, full
    )

    # ── Tag Normalization ─────────────────────────────────────────
    fast_model = get_model("fast", project_dir)
    aliases = await _normalize_tags(wiki_dir, client, fast_model, agents_md)
    tags_normalized = sum(1 for k, v in aliases.items() if k != v)

    # ── Pass 2 ────────────────────────────────────────────────────
    concepts_generated = await _pass2(
        wiki_dir, project_dir, client, agents_md, state, aliases
    )

    # ── Pass 3 ────────────────────────────────────────────────────
    await _pass3(wiki_dir, project_dir, client, agents_md)

    # ── Finalize ──────────────────────────────────────────────────
    state.save(wiki_dir)

    try:
        git_add_and_commit(
            project_dir,
            f"klore compile: {pass1_stats['sources_processed']} sources, "
            f"{concepts_generated} concepts",
        )
    except RuntimeError as exc:
        click.echo(f"  warning: git commit failed: {exc}", err=True)

    stats = {
        "sources_processed": pass1_stats["sources_processed"],
        "concepts_generated": concepts_generated,
        "tags_normalized": tags_normalized,
        "pass1_skipped": pass1_stats["pass1_skipped"],
        "pass1_errors": pass1_stats["pass1_errors"],
    }

    click.echo(
        f"Compilation complete: {stats['sources_processed']} sources, "
        f"{stats['concepts_generated']} concepts, "
        f"{stats['tags_normalized']} tags normalized.",
        err=True,
    )

    return stats
