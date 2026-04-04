"""Q&A module — index-first query with Director routing."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import click

from klore.git import git_add_and_commit
from klore.ingester import slugify
from klore.log import append_log, read_recent_log
from klore.models import get_client, get_model


def _fill_prompt(template: str, **kwargs: str) -> str:
    """Replace {key} placeholders without Python's format() brace conflicts."""
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


def _strip_code_fences(text: str) -> str:
    """Strip wrapping ```markdown ... ``` fences from LLM output."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_nl = stripped.index("\n") if "\n" in stripped else len(stripped)
        stripped = stripped[first_nl + 1:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()


def _parse_director_json(raw: str) -> dict | None:
    """Extract and parse JSON from Director response. Returns None on failure."""
    text = _strip_code_fences(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _fallback_pages(wiki_dir: Path) -> list[str]:
    """Return all concept and entity page paths (relative to wiki/) as fallback."""
    pages: list[str] = []
    for subdir in ("concepts", "entities"):
        d = wiki_dir / subdir
        if d.is_dir():
            for md in sorted(d.rglob("*.md")):
                rel = md.relative_to(wiki_dir)
                # Strip .md for consistency with Director output
                pages.append(str(rel.with_suffix("")))
    return pages


def _load_selected_pages(wiki_dir: Path, page_paths: list[str]) -> str:
    """Read the specified pages and concatenate with headers."""
    parts: list[str] = []
    for page in page_paths:
        # Add .md extension if not present
        if not page.endswith(".md"):
            page_with_ext = page + ".md"
        else:
            page_with_ext = page

        full_path = wiki_dir / page_with_ext
        if full_path.is_file():
            content = full_path.read_text(encoding="utf-8")
            parts.append(f"=== wiki/{page_with_ext} ===\n{content}")
        else:
            parts.append(f"=== wiki/{page_with_ext} ===\n(page not found)")
    return "\n\n".join(parts)


async def ask(project_dir: Path, question: str, save: bool = False) -> str:
    """Index-first query with Director routing."""
    wiki_dir = project_dir / "wiki"
    client = get_client(project_dir)

    # --- Step 1: Director Query Plan ------------------------------------------

    # Read index
    index_path = wiki_dir / "index.md"
    index_content = (
        index_path.read_text(encoding="utf-8") if index_path.exists() else "(no index)"
    )

    # Read recent log
    recent_log = read_recent_log(wiki_dir, n=20)

    # Read agents.md
    agents_path = project_dir / ".klore" / "agents.md"
    agents_md = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""

    # Build Director prompt
    director_template_path = Path(__file__).parent / "prompts" / "director_query.md"
    director_template = director_template_path.read_text(encoding="utf-8")
    director_prompt = _fill_prompt(director_template,
        question=question,
        index_content=index_content,
        recent_log=recent_log,
        agents_md=agents_md,
    )

    # Call Director model
    director_model = get_model("director", project_dir)
    director_response = client.chat.completions.create(
        model=director_model,
        messages=[{"role": "user", "content": director_prompt}],
    )
    director_raw = director_response.choices[0].message.content

    # Parse Director JSON
    query_plan = _parse_director_json(director_raw)

    if query_plan is None:
        click.echo(
            "Warning: Director JSON parsing failed — falling back to all concept/entity pages.",
            err=True,
        )
        relevant_pages = _fallback_pages(wiki_dir)
        query_plan = {
            "relevant_pages": relevant_pages,
            "strategy": "fallback",
            "emphasis": "Answer as best as possible from available pages",
            "gaps": [],
            "should_file": False,
            "reasoning": "Director output could not be parsed; loading all concept/entity pages.",
        }
    else:
        relevant_pages = query_plan.get("relevant_pages", [])
        if not relevant_pages:
            relevant_pages = _fallback_pages(wiki_dir)
            query_plan["relevant_pages"] = relevant_pages

    # --- Step 2: Read Selected Pages ------------------------------------------

    selected_pages = _load_selected_pages(wiki_dir, relevant_pages)

    # --- Step 3: Synthesize Answer --------------------------------------------

    ask_template_path = Path(__file__).parent / "prompts" / "ask.md"
    ask_template = ask_template_path.read_text(encoding="utf-8")
    ask_prompt = _fill_prompt(ask_template,
        agents_md=agents_md,
        query_plan=json.dumps(query_plan, indent=2),
        selected_pages=selected_pages,
        question=question,
    )

    strong_model = get_model("strong", project_dir)
    answer_response = client.chat.completions.create(
        model=strong_model,
        messages=[{"role": "user", "content": ask_prompt}],
    )
    answer = _strip_code_fences(answer_response.choices[0].message.content)

    # --- Step 4: File Report (if requested or Director recommends) -------------

    should_file = save or query_plan.get("should_file", False)

    if should_file:
        slug = slugify(question)
        report_dir = wiki_dir / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{slug}.md"

        frontmatter = (
            "---\n"
            f'title: "{question}"\n'
            f'date: "{date.today().isoformat()}"\n'
            "type: report\n"
            "---\n\n"
        )
        report_path.write_text(frontmatter + answer, encoding="utf-8")
        click.echo(f"Report saved to {report_path.relative_to(project_dir)}")

        # Log the query
        details = f"Pages consulted: {', '.join(relevant_pages[:5])}"
        editorial_notes = query_plan.get("reasoning", "")
        append_log(wiki_dir, "query", question[:60], details, editorial_notes)

        git_add_and_commit(
            project_dir,
            f"wiki: add report — {question[:60]}",
        )

    return answer
