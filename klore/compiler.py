"""Seven-step director-driven compilation engine — the heart of Klore.

Step 1: EXTRACT — convert raw files to markdown (concurrent).
Step 2: EDITORIAL BRIEF — Director reads extractions and produces editorial briefs.
Step 3: TAG NORMALIZE — merge synonym tags via LLM (fast tier).
Step 4: BUILD — write source summaries, entity pages, concept pages (concurrent, strong tier).
Step 5: REVIEW — Director reviews pages created in Step 4.
Step 6: INDEX & LOG — generate index, append log entries, build link graph.
Step 7: OVERVIEW — Director writes/updates wiki/overview.md.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import yaml

from klore.git import git_add_and_commit
from klore.hash import hash_file, hash_string
from klore.ingester import IngestionError, convert_to_markdown, slugify
from klore.log import append_log, read_recent_log
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


def _fill_prompt(template: str, **kwargs: str) -> str:
    """Replace {key} placeholders without Python's format() brace conflicts.

    Unlike str.format(), this doesn't choke on JSON braces in prompt templates.
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


def _read_agents_md(project_dir: Path) -> str:
    """Read the agents.md schema file from .klore/, returning empty string if absent."""
    agents_path = project_dir / ".klore" / "agents.md"
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
        if not isinstance(fm, dict):
            continue
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
        if not isinstance(fm, dict):
            continue
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
        if md_file.name.lower() in ("index.md",):
            continue
        slug = md_file.stem
        fm = _parse_frontmatter(md_file.read_text("utf-8"))
        title = fm.get("title", slug)
        tags = fm.get("tags", [])
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"- {prefix}{slug}: {title}{tag_str}")
    return "\n".join(lines) if lines else "(none)"


def _list_entity_files_summary(entities_dir: Path) -> str:
    """List entity pages for index prompt."""
    if not entities_dir.is_dir():
        return "(none)"
    lines: list[str] = []
    for md_file in sorted(entities_dir.glob("*.md")):
        slug = md_file.stem
        fm = _parse_frontmatter(md_file.read_text("utf-8"))
        title = fm.get("title", slug)
        entity_type = fm.get("entity_type", "unknown")
        lines.append(f"- entities/{slug}: {title} ({entity_type})")
    return "\n".join(lines) if lines else "(none)"


def _read_index(wiki_dir: Path) -> str:
    """Read wiki/index.md content, returning empty string if absent."""
    index_path = wiki_dir / "index.md"
    if index_path.is_file():
        return index_path.read_text("utf-8")
    return ""


def _strip_code_fences(text: str) -> str:
    """Strip wrapping ```markdown ... ``` fences from LLM output."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_nl = stripped.index("\n") if "\n" in stripped else len(stripped)
        stripped = stripped[first_nl + 1:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()


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


# ── Step 1: Extract ─────────────────────────────────────────────────


async def _extract_source(
    file_path: Path,
    project_dir: Path,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any] | None:
    """Convert a single source file to markdown.

    Returns a dict with {filename, content, rel_path, file_path} or None on error.
    """
    async with semaphore:
        rel_path = str(file_path.relative_to(project_dir))
        filename = file_path.name

        try:
            content = await asyncio.to_thread(convert_to_markdown, file_path)
        except IngestionError as exc:
            click.echo(f"  warning: skipping {filename}: {exc}", err=True)
            return None

        return {
            "filename": filename,
            "content": content,
            "rel_path": rel_path,
            "file_path": file_path,
        }


async def _step1_extract(
    project_dir: Path,
    raw_dir: Path,
    state: CompileState,
    full: bool,
) -> tuple[list[dict[str, Any]], int, int]:
    """Step 1: Extract raw files to markdown.

    Returns (extractions, skipped_count, error_count).
    """
    if full:
        sources = sorted(p for p in raw_dir.rglob("*") if p.is_file())
    else:
        new, changed, _removed = state.diff_sources(raw_dir)
        sources = sorted([project_dir / p for p in new + changed])

    if not sources:
        click.echo("Step 1 (Extract): no sources to process.", err=True)
        return [], 0, 0

    click.echo(f"Step 1 (Extract): converting {len(sources)} sources...", err=True)

    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [_extract_source(src, project_dir, semaphore) for src in sources]
    results = await asyncio.gather(*tasks)

    extractions = [r for r in results if r is not None]
    errors = sum(1 for r in results if r is None)

    click.echo(
        f"Step 1 (Extract): done — {len(extractions)} extracted, {errors} errors.",
        err=True,
    )
    return extractions, 0, errors


# ── Step 2: Editorial Brief ─────────────────────────────────────────


def _default_brief(filename: str) -> dict[str, Any]:
    """Return a minimal default editorial brief when JSON parsing fails."""
    return {
        "summary": f"Source file: {filename}",
        "key_takeaways": [],
        "novelty": "Unknown — editorial brief generation failed.",
        "contradictions": [],
        "emphasis": "Provide a balanced summary.",
        "pages": [],
        "entities": [],
        "concepts": [],
        "existing_pages_to_update": [],
        "questions_raised": [],
        "suggested_sources": [],
    }


async def _get_editorial_brief(
    extraction: dict[str, Any],
    wiki_dir: Path,
    client: Any,
    director_model: str,
    agents_md: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Call Director to produce an editorial brief for a single extraction."""
    async with semaphore:
        index_content = _read_index(wiki_dir)
        recent_log = read_recent_log(wiki_dir, n=20)

        # Count existing pages for scale context
        source_count = len(list((wiki_dir / "sources").glob("*.md"))) if (wiki_dir / "sources").is_dir() else 0
        concept_count = len(list((wiki_dir / "concepts").glob("*.md"))) if (wiki_dir / "concepts").is_dir() else 0
        entity_count = len(list((wiki_dir / "entities").glob("*.md"))) if (wiki_dir / "entities").is_dir() else 0

        prompt_template = _read_prompt("director_brief.md")
        user_prompt = _fill_prompt(prompt_template,
            source_count=str(source_count),
            concept_count=str(concept_count),
            entity_count=str(entity_count),
            index_content=index_content or "(empty wiki)",
            recent_log=recent_log,
            agents_md=agents_md or "(no schema defined)",
            filename=extraction["filename"],
            source_content=extraction["content"],
        )

        output = await _llm_call(
            client, director_model,
            "You are the editorial director of a knowledge wiki.",
            user_prompt,
        )

        # Parse JSON response
        cleaned = _strip_code_fences(output)
        # Also strip json fences specifically
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            brief = json.loads(cleaned)
        except json.JSONDecodeError:
            click.echo(
                f"  warning: could not parse editorial brief for "
                f"{extraction['filename']}, using defaults.",
                err=True,
            )
            brief = _default_brief(extraction["filename"])

        # Attach the filename for tracking
        brief["_filename"] = extraction["filename"]
        brief["_rel_path"] = extraction["rel_path"]
        return brief


async def _step2_editorial_briefs(
    extractions: list[dict[str, Any]],
    wiki_dir: Path,
    project_dir: Path,
    client: Any,
    agents_md: str,
) -> list[dict[str, Any]]:
    """Step 2: Get editorial briefs from the Director for each extraction."""
    if not extractions:
        return []

    director_model = get_model("director", project_dir)
    click.echo(
        f"Step 2 (Editorial Brief): requesting {len(extractions)} briefs...",
        err=True,
    )

    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [
        _get_editorial_brief(
            ext, wiki_dir, client, director_model, agents_md, semaphore,
        )
        for ext in extractions
    ]
    briefs = await asyncio.gather(*tasks)

    click.echo(
        f"Step 2 (Editorial Brief): done — {len(briefs)} briefs produced.",
        err=True,
    )
    return list(briefs)


# ── Step 3: Tag Normalize ───────────────────────────────────────────


async def _step3_normalize_tags(
    wiki_dir: Path,
    client: Any,
    fast_model: str,
) -> dict[str, str]:
    """Step 3: Normalize tags across all source summaries via LLM."""
    all_tags = _collect_all_tags(wiki_dir / "sources")
    if not all_tags:
        click.echo("Step 3 (Tag Normalize): no tags found, skipping.", err=True)
        return {}

    click.echo(
        f"Step 3 (Tag Normalize): {len(all_tags)} unique tags...", err=True
    )

    prompt_template = _read_prompt("normalize_tags.md")
    user_prompt = prompt_template.replace(
        "{tag_list}", "\n".join(f"- {t}" for t in all_tags)
    )

    output = await _llm_call(
        client, fast_model, "You are a tag normalizer.", user_prompt
    )

    # Parse JSON from response — strip markdown fences if present
    cleaned = output.strip()
    if cleaned.startswith("```"):
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
        f"Step 3 (Tag Normalize): done — {normalized_count} tags merged.",
        err=True,
    )
    return aliases


# ── Step 4: Build ───────────────────────────────────────────────────


# ── Step 4a: Source Summaries ────────────────────────────────────────


async def _build_source_summary(
    extraction: dict[str, Any],
    brief: dict[str, Any],
    wiki_dir: Path,
    project_dir: Path,
    client: Any,
    strong_model: str,
    agents_md: str,
    existing_tags: list[str],
    state: CompileState,
    semaphore: asyncio.Semaphore,
) -> bool:
    """Build a single source summary guided by the editorial brief.

    Returns True on success.
    """
    async with semaphore:
        filename = extraction["filename"]
        file_path = extraction["file_path"]

        # Format brief as JSON string for the prompt
        brief_json = json.dumps(
            {k: v for k, v in brief.items() if not k.startswith("_")},
            indent=2,
        )

        prompt_template = _read_prompt("compile_source.md")
        user_prompt = _fill_prompt(prompt_template, 
            agents_md=agents_md,
            editorial_brief=brief_json,
            existing_tags=", ".join(existing_tags) if existing_tags else "(none yet)",
            filename=filename,
            source_content=extraction["content"],
        )

        output = await _llm_call(
            client, strong_model, "You are a knowledge compiler.", user_prompt
        )

        # Validate
        if not _validate_source_output(output):
            retry_msg = (
                "Your output was malformed. Please produce valid markdown "
                "starting with YAML frontmatter."
            )
            output = await _llm_call(
                client, strong_model,
                "You are a knowledge compiler.",
                user_prompt + "\n\n" + retry_msg,
            )
            if not _validate_source_output(output):
                click.echo(
                    f"  warning: malformed output for {filename}, skipping",
                    err=True,
                )
                return False

        # Write atomically to wiki/sources/{slug}.md
        slug = slugify(file_path.stem)
        dest = wiki_dir / "sources" / f"{slug}.md"
        _atomic_write(dest, _strip_code_fences(output))

        # Update state
        file_hash = await asyncio.to_thread(hash_file, file_path)
        state.update_hash(extraction["rel_path"], file_hash)

        return True


async def _step4a_source_summaries(
    extractions: list[dict[str, Any]],
    briefs: list[dict[str, Any]],
    wiki_dir: Path,
    project_dir: Path,
    client: Any,
    agents_md: str,
    state: CompileState,
) -> int:
    """Step 4a: Build source summaries guided by editorial briefs."""
    if not extractions:
        return 0

    strong_model = get_model("strong", project_dir)
    (wiki_dir / "sources").mkdir(parents=True, exist_ok=True)
    existing_tags = _collect_all_tags(wiki_dir / "sources")

    click.echo(
        f"Step 4a (Source Summaries): building {len(extractions)} summaries...",
        err=True,
    )

    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [
        _build_source_summary(
            ext, brief, wiki_dir, project_dir, client, strong_model,
            agents_md, existing_tags, state, semaphore,
        )
        for ext, brief in zip(extractions, briefs)
    ]
    results = await asyncio.gather(*tasks)

    processed = sum(1 for r in results if r)
    click.echo(
        f"Step 4a (Source Summaries): done — {processed} summaries written.",
        err=True,
    )
    return processed


# ── Step 4b: Entity Pages ───────────────────────────────────────────


def _collect_entities_from_briefs(
    briefs: list[dict[str, Any]],
    extractions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Collect entity recommendations from editorial briefs.

    Reads from unified ``pages`` array (new schema) and falls back to
    ``entities`` array (old schema). Filters out items the Director
    marked as skip or low significance.

    Returns a dict keyed by entity slug, with merged info from all briefs.
    """
    entities: dict[str, dict[str, Any]] = {}

    for brief, extraction in zip(briefs, extractions):
        # Collect from unified pages array (new) + entities array (backward compat)
        entity_list: list[dict[str, Any]] = []
        for page_info in brief.get("pages", []):
            if page_info.get("page_type") == "entity":
                entity_list.append(page_info)
        entity_list.extend(brief.get("entities", []))

        for entity_info in entity_list:
            # Filter: skip items the Director marked as skip or low significance
            if entity_info.get("action") == "skip":
                continue
            if entity_info.get("significance") == "low":
                continue

            slug = entity_info.get("slug", slugify(entity_info.get("name", "")))
            if not slug:
                continue

            if slug not in entities:
                entities[slug] = {
                    "name": entity_info.get("name", slug),
                    "slug": slug,
                    "entity_type": entity_info.get("entity_type", "unknown"),
                    "action": entity_info.get("action", "create"),
                    "reasons": [],
                    "source_filenames": [],
                    "source_slugs": [],
                }

            reason = entity_info.get("reason") or entity_info.get("justification", "")
            if reason:
                entities[slug]["reasons"].append(reason)
            entities[slug]["source_filenames"].append(extraction["filename"])
            source_slug = slugify(extraction["file_path"].stem)
            if source_slug not in entities[slug]["source_slugs"]:
                entities[slug]["source_slugs"].append(source_slug)

            # Upgrade action to "update" if any brief says "update"
            if entity_info.get("action") == "update":
                entities[slug]["action"] = "update"

    return entities


async def _build_entity_page(
    entity_info: dict[str, Any],
    wiki_dir: Path,
    client: Any,
    strong_model: str,
    agents_md: str,
    known_entities: list[str],
    known_concepts: list[str],
    state: CompileState,
    semaphore: asyncio.Semaphore,
) -> bool:
    """Build or update a single entity page.

    Returns True on success.
    """
    async with semaphore:
        slug = entity_info["slug"]
        entity_name = entity_info["name"]
        entity_type = entity_info["entity_type"]
        action = entity_info["action"]

        # Read existing entity page if present
        existing_path = wiki_dir / "entities" / f"{slug}.md"
        existing_page = ""
        if existing_path.is_file():
            existing_page = existing_path.read_text("utf-8")

        # Gather source summaries that mention this entity
        source_mentions_parts: list[str] = []
        sources_dir = wiki_dir / "sources"
        for source_slug in entity_info["source_slugs"]:
            source_file = sources_dir / f"{source_slug}.md"
            if source_file.is_file():
                content = source_file.read_text("utf-8")
                source_mentions_parts.append(
                    f"### From {source_slug}\n\n{content}"
                )
        source_mentions = (
            "\n\n---\n\n".join(source_mentions_parts)
            if source_mentions_parts
            else "(no source summaries available yet)"
        )

        # Director's notes from the briefs
        director_notes = "\n".join(
            f"- {r}" for r in entity_info["reasons"]
        ) or "(no specific notes)"

        prompt_template = _read_prompt("compile_entity.md")
        user_prompt = _fill_prompt(prompt_template, 
            agents_md=agents_md,
            entity_name=entity_name,
            entity_type=entity_type,
            action=action,
            director_notes=director_notes,
            source_mentions=source_mentions,
            known_entities=", ".join(f"[[{e}]]" for e in known_entities)
            if known_entities
            else "(none)",
            known_concepts=", ".join(f"[[{c}]]" for c in known_concepts)
            if known_concepts
            else "(none)",
            existing_page=existing_page or "(new entity)",
        )

        output = await _llm_call(
            client, strong_model, "You are a knowledge compiler.", user_prompt
        )

        if not _validate_concept_output(output):
            retry_msg = (
                "Your output was malformed. Please produce valid markdown "
                "starting with YAML frontmatter."
            )
            output = await _llm_call(
                client, strong_model,
                "You are a knowledge compiler.",
                user_prompt + "\n\n" + retry_msg,
            )
            if not _validate_concept_output(output):
                click.echo(
                    f"  warning: malformed output for entity {entity_name}, skipping",
                    err=True,
                )
                return False

        _atomic_write(existing_path, _strip_code_fences(output))

        # Update state
        state.update_entity_sources(slug, entity_info["source_slugs"])

        return True


async def _step4b_entity_pages(
    briefs: list[dict[str, Any]],
    extractions: list[dict[str, Any]],
    wiki_dir: Path,
    client: Any,
    project_dir: Path,
    agents_md: str,
    state: CompileState,
) -> int:
    """Step 4b: Create/update entity pages as directed by briefs."""
    entities = _collect_entities_from_briefs(briefs, extractions)

    if not entities:
        click.echo("Step 4b (Entity Pages): no entities to create.", err=True)
        return 0

    strong_model = get_model("strong", project_dir)
    (wiki_dir / "entities").mkdir(parents=True, exist_ok=True)

    # Gather known entities and concepts for cross-linking
    known_entities = sorted(entities.keys())
    concepts_dir = wiki_dir / "concepts"
    known_concepts = []
    if concepts_dir.is_dir():
        known_concepts = sorted(f.stem for f in concepts_dir.glob("*.md"))

    click.echo(
        f"Step 4b (Entity Pages): building {len(entities)} entity pages...",
        err=True,
    )

    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [
        _build_entity_page(
            entity_info, wiki_dir, client, strong_model, agents_md,
            known_entities, known_concepts, state, semaphore,
        )
        for entity_info in entities.values()
    ]
    results = await asyncio.gather(*tasks)

    created = sum(1 for r in results if r)
    click.echo(
        f"Step 4b (Entity Pages): done — {created} entity pages written.",
        err=True,
    )
    return created


# ── Step 4c: Concept Pages ──────────────────────────────────────────


async def _build_concept_page(
    tag: str,
    source_files: list[Path],
    wiki_dir: Path,
    client: Any,
    strong_model: str,
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
        user_prompt = _fill_prompt(prompt_template, 
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
            client, strong_model, "You are a knowledge compiler.", user_prompt
        )

        # Validate
        if not _validate_concept_output(output):
            retry_msg = (
                "Your output was malformed. Please produce valid markdown "
                "starting with YAML frontmatter."
            )
            output = await _llm_call(
                client, strong_model,
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
        _atomic_write(existing_path, _strip_code_fences(output))

        # Update state
        state.update_concept_sources(concept_slug, source_slugs)

        return True


async def _step4c_concept_pages(
    wiki_dir: Path,
    project_dir: Path,
    client: Any,
    agents_md: str,
    state: CompileState,
    aliases: dict[str, str],
    briefs: list[dict[str, Any]] | None = None,
) -> int:
    """Step 4c: Synthesize concept articles.

    Uses Director recommendations from editorial briefs as the primary signal.
    Falls back to tag-frequency (3+ sources) as a safety net for concepts
    the Director might miss.
    """
    strong_model = get_model("strong", project_dir)
    sources_dir = wiki_dir / "sources"

    # Group sources by normalized tags (used for finding contributing sources)
    groups = _group_sources_by_tag(sources_dir, aliases)

    # Collect Director-recommended concepts from briefs
    recommended: dict[str, dict[str, Any]] = {}
    for brief in (briefs or []):
        # Read from unified pages array (new) + concepts array (backward compat)
        concept_list: list[dict[str, Any]] = []
        for page_info in brief.get("pages", []):
            if page_info.get("page_type") == "concept":
                concept_list.append(page_info)
        concept_list.extend(brief.get("concepts", []))

        for concept_info in concept_list:
            if concept_info.get("action") == "skip":
                continue
            if concept_info.get("significance") == "low":
                continue
            name = concept_info.get("name", "")
            slug = concept_info.get("slug", slugify(name))
            if slug and slug not in recommended:
                recommended[slug] = concept_info

    # Safety net: also include tag-based concepts with 3+ sources
    for tag, files in groups.items():
        slug = slugify(tag)
        if len(files) >= 3 and slug not in recommended:
            recommended[slug] = {
                "name": tag.replace("-", " ").title(),
                "slug": slug,
            }

    # Build eligible dict: concept slug → list of contributing source files
    eligible: dict[str, list[Path]] = {}
    for slug, info in recommended.items():
        name = info.get("name", slug)
        tag_key = name.lower().replace(" ", "-")
        # Try tag groups first for best source matching
        matching = groups.get(tag_key, []) or groups.get(slug, [])
        if not matching:
            # Scan all source summaries as fallback
            matching = sorted(sources_dir.glob("*.md")) if sources_dir.is_dir() else []
        if matching:
            eligible[tag_key] = matching

    if not eligible:
        click.echo(
            "Step 4c (Concept Pages): no concepts to create, skipping.",
            err=True,
        )
        return 0

    click.echo(
        f"Step 4c (Concept Pages): synthesizing {len(eligible)} concepts...",
        err=True,
    )

    (wiki_dir / "concepts").mkdir(parents=True, exist_ok=True)

    known_concepts = sorted(slugify(tag) for tag in eligible)

    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [
        _build_concept_page(
            tag, files, wiki_dir, client, strong_model,
            agents_md, known_concepts, state, semaphore,
        )
        for tag, files in sorted(eligible.items())
    ]
    results = await asyncio.gather(*tasks)

    generated = sum(1 for r in results if r)
    click.echo(
        f"Step 4c (Concept Pages): done — {generated} concepts generated.",
        err=True,
    )
    return generated


# ── Step 5: Review ──────────────────────────────────────────────────


async def _step5_review(
    extractions: list[dict[str, Any]],
    briefs: list[dict[str, Any]],
    wiki_dir: Path,
    project_dir: Path,
    client: Any,
) -> list[dict[str, Any]]:
    """Step 5: Director reviews the pages created/updated in Step 4.

    Returns list of review results (one per source).
    For v1, we just log issues found.
    """
    if not extractions:
        return []

    director_model = get_model("director", project_dir)
    click.echo(
        f"Step 5 (Review): Director reviewing {len(extractions)} builds...",
        err=True,
    )

    prompt_template = _read_prompt("director_review.md")
    reviews: list[dict[str, Any]] = []

    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)

    async def _review_one(
        extraction: dict[str, Any],
        brief: dict[str, Any],
    ) -> dict[str, Any]:
        async with semaphore:
            slug = slugify(extraction["file_path"].stem)

            # Read source summary
            source_file = wiki_dir / "sources" / f"{slug}.md"
            source_summary = ""
            if source_file.is_file():
                source_summary = source_file.read_text("utf-8")

            # Gather entity pages from this brief
            entity_pages_parts: list[str] = []
            for entity_info in brief.get("entities", []):
                entity_slug = entity_info.get(
                    "slug", slugify(entity_info.get("name", ""))
                )
                entity_file = wiki_dir / "entities" / f"{entity_slug}.md"
                if entity_file.is_file():
                    entity_pages_parts.append(
                        f"### {entity_slug}\n\n{entity_file.read_text('utf-8')}"
                    )
            entity_pages = (
                "\n\n---\n\n".join(entity_pages_parts)
                if entity_pages_parts
                else "(no entity pages)"
            )

            # Gather concept pages (simplified — check concepts dir)
            concept_pages_parts: list[str] = []
            concepts_dir = wiki_dir / "concepts"
            if concepts_dir.is_dir():
                # Read concept pages that reference this source
                for concept_file in concepts_dir.glob("*.md"):
                    content = concept_file.read_text("utf-8")
                    if slug in content:
                        concept_pages_parts.append(
                            f"### {concept_file.stem}\n\n{content}"
                        )
            concept_pages = (
                "\n\n---\n\n".join(concept_pages_parts)
                if concept_pages_parts
                else "(no concept pages)"
            )

            brief_json = json.dumps(
                {k: v for k, v in brief.items() if not k.startswith("_")},
                indent=2,
            )

            user_prompt = _fill_prompt(prompt_template, 
                editorial_brief=brief_json,
                source_summary=source_summary or "(not written)",
                entity_pages=entity_pages,
                concept_pages=concept_pages,
            )

            output = await _llm_call(
                client, director_model,
                "You are the editorial director reviewing wiki changes.",
                user_prompt,
            )

            # Parse review JSON
            cleaned = _strip_code_fences(output)
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned)
                cleaned = cleaned.strip()

            try:
                review = json.loads(cleaned)
            except json.JSONDecodeError:
                review = {
                    "approved": True,
                    "issues": [],
                    "editorial_notes": "Review parsing failed — auto-approved.",
                }

            return review

    tasks = [
        _review_one(ext, brief)
        for ext, brief in zip(extractions, briefs)
    ]
    reviews = await asyncio.gather(*tasks)

    # Log any issues found (v1: just log, don't re-run builds)
    total_issues = sum(len(r.get("issues", [])) for r in reviews)
    if total_issues:
        click.echo(
            f"Step 5 (Review): Director found {total_issues} issues "
            f"(logged for future improvement).",
            err=True,
        )
    else:
        click.echo("Step 5 (Review): Director approved all pages.", err=True)

    return list(reviews)


# ── Step 6: Index & Log ─────────────────────────────────────────────


async def _step6_index_and_log(
    wiki_dir: Path,
    project_dir: Path,
    client: Any,
    agents_md: str,
    extractions: list[dict[str, Any]],
    briefs: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    sources_processed: int,
    entities_created: int,
    concepts_generated: int,
) -> None:
    """Step 6: Generate index, append log entries, build link graph."""
    strong_model = get_model("strong", project_dir)

    click.echo("Step 6 (Index & Log): generating index...", err=True)

    # Gather listings
    concept_list = _list_files_summary(wiki_dir / "concepts", prefix="concepts/")
    source_list = _list_files_summary(wiki_dir / "sources", prefix="sources/")
    entity_list = _list_entity_files_summary(wiki_dir / "entities")

    reports_dir = wiki_dir / "reports"
    report_list = _list_files_summary(reports_dir, prefix="reports/")

    concept_count = (
        len(list((wiki_dir / "concepts").glob("*.md")))
        if (wiki_dir / "concepts").is_dir()
        else 0
    )
    source_count = (
        len(list((wiki_dir / "sources").glob("*.md")))
        if (wiki_dir / "sources").is_dir()
        else 0
    )
    entity_count = (
        len(list((wiki_dir / "entities").glob("*.md")))
        if (wiki_dir / "entities").is_dir()
        else 0
    )
    report_count = (
        len(list(reports_dir.glob("*.md"))) if reports_dir.is_dir() else 0
    )

    # Generate single wiki/index.md
    prompt_template = _read_prompt("compile_index.md")
    user_prompt = _fill_prompt(prompt_template, 
        agents_md=agents_md,
        concept_count=concept_count,
        concept_list=concept_list,
        entity_count=entity_count,
        entity_list=entity_list,
        source_count=source_count,
        source_list=source_list,
        report_count=report_count,
        report_list=report_list,
    )

    output = await _llm_call(
        client, strong_model, "You are a knowledge compiler.", user_prompt
    )
    _atomic_write(wiki_dir / "index.md", _strip_code_fences(output))

    # Append log entries for each source processed
    for ext, brief, review in zip(extractions, briefs, reviews):
        filename = ext["filename"]
        slug = slugify(ext["file_path"].stem)

        # Collect pages touched by this source
        pages_touched = [f"sources/{slug}.md"]
        for entity_info in brief.get("entities", []):
            entity_slug = entity_info.get(
                "slug", slugify(entity_info.get("name", ""))
            )
            if entity_slug:
                pages_touched.append(f"entities/{entity_slug}.md")

        entity_count_for_source = len(brief.get("entities", []))
        details = (
            f"Created source summary for {filename}. "
            f"Entities: {entity_count_for_source}."
        )

        editorial_notes = review.get("editorial_notes")

        append_log(
            wiki_dir,
            action="ingest",
            title=filename,
            details=details,
            editorial_notes=editorial_notes,
        )

    # Build link graph
    link_graph = _build_link_graph(wiki_dir)
    meta_dir = wiki_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "link-graph.json").write_text(
        json.dumps(link_graph, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    click.echo(
        f"Step 6 (Index & Log): done — index generated, "
        f"{len(extractions)} log entries appended.",
        err=True,
    )


# ── Step 7: Overview ────────────────────────────────────────────────


async def _step7_overview(
    wiki_dir: Path,
    project_dir: Path,
    client: Any,
    agents_md: str,
) -> None:
    """Step 7: Director writes/updates wiki/overview.md."""
    director_model = get_model("director", project_dir)

    click.echo("Step 7 (Overview): Director writing overview...", err=True)

    # Read current overview
    overview_path = wiki_dir / "overview.md"
    current_overview = ""
    if overview_path.is_file():
        current_overview = overview_path.read_text("utf-8")

    index_content = _read_index(wiki_dir)
    recent_log = read_recent_log(wiki_dir, n=20)

    prompt_template = _read_prompt("director_overview.md")
    user_prompt = _fill_prompt(prompt_template, 
        current_overview=current_overview or "(no overview yet)",
        index_content=index_content or "(empty wiki)",
        recent_log=recent_log,
        agents_md=agents_md or "(no schema defined)",
    )

    output = await _llm_call(
        client, director_model,
        "You are the editorial director of a knowledge wiki.",
        user_prompt,
    )

    _atomic_write(overview_path, _strip_code_fences(output))

    click.echo("Step 7 (Overview): done — overview written.", err=True)


# ── Main entry point ─────────────────────────────────────────────────


async def compile_wiki(project_dir: Path, full: bool = False) -> dict:
    """Run the seven-step director-driven compilation. Returns stats dict."""
    wiki_dir = project_dir / "wiki"
    raw_dir = project_dir / "raw"

    # Ensure directories exist
    wiki_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Load state and agents
    state = CompileState.load(wiki_dir)
    agents_md = _read_agents_md(project_dir)
    prompt_hash = _compute_prompt_hash(agents_md)

    # Check if full recompile needed due to prompt changes
    if state.needs_full_recompile(prompt_hash):
        click.echo(
            "Prompts or agents.md changed — forcing full recompile.", err=True
        )
        full = True
    state.set_prompt_hash(prompt_hash)

    # Initialize client
    client = get_client(project_dir)

    # ── Step 1: Extract ──────────────────────────────────────────
    extractions, pass1_skipped, pass1_errors = await _step1_extract(
        project_dir, raw_dir, state, full
    )

    # ── Step 2: Editorial Briefs ─────────────────────────────────
    briefs = await _step2_editorial_briefs(
        extractions, wiki_dir, project_dir, client, agents_md
    )

    # ── Step 4a: Source Summaries ──────────────────────────────────
    # Write source summaries first — tag normalization and concept
    # synthesis both need them on disk.
    sources_processed = await _step4a_source_summaries(
        extractions, briefs, wiki_dir, project_dir, client, agents_md, state
    )

    # ── Step 3: Tag Normalize ────────────────────────────────────
    # Run AFTER source summaries are written so we have tags to normalize.
    fast_model = get_model("fast", project_dir)
    aliases = await _step3_normalize_tags(wiki_dir, client, fast_model)

    # ── Step 4b+4c: Entity + Concept Pages ───────────────────────
    # Run entity pages and concept pages concurrently.
    entities_created, concepts_generated = await asyncio.gather(
        _step4b_entity_pages(
            briefs, extractions, wiki_dir, client, project_dir, agents_md, state
        ),
        _step4c_concept_pages(
            wiki_dir, project_dir, client, agents_md, state, aliases, briefs
        ),
    )

    # ── Step 5: Review ───────────────────────────────────────────
    reviews = await _step5_review(
        extractions, briefs, wiki_dir, project_dir, client
    )

    # ── Step 6: Index & Log ──────────────────────────────────────
    await _step6_index_and_log(
        wiki_dir, project_dir, client, agents_md,
        extractions, briefs, reviews,
        sources_processed, entities_created, concepts_generated,
    )

    # ── Step 7: Overview ─────────────────────────────────────────
    await _step7_overview(wiki_dir, project_dir, client, agents_md)

    # ── Finalize ─────────────────────────────────────────────────
    state.save(wiki_dir)

    tags_normalized = sum(1 for k, v in aliases.items() if k != v)

    try:
        git_add_and_commit(
            project_dir,
            f"klore compile: {sources_processed} sources, "
            f"{concepts_generated} concepts, {entities_created} entities",
        )
    except RuntimeError as exc:
        click.echo(f"  warning: git commit failed: {exc}", err=True)

    stats = {
        "sources_processed": sources_processed,
        "concepts_generated": concepts_generated,
        "entities_created": entities_created,
        "tags_normalized": tags_normalized,
        "pass1_skipped": pass1_skipped,
        "pass1_errors": pass1_errors,
    }

    click.echo(
        f"Compilation complete: {stats['sources_processed']} sources, "
        f"{stats['concepts_generated']} concepts, "
        f"{stats['entities_created']} entities, "
        f"{stats['tags_normalized']} tags normalized.",
        err=True,
    )

    return stats
