"""Q&A module — answers questions against the compiled wiki."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import click

from klore.git import git_add_and_commit
from klore.ingester import slugify
from klore.models import get_client, get_context_limit, get_model

CONTEXT_BUDGET_RATIO = 0.80  # use at most 80% of the model's context for wiki content
CHARS_PER_TOKEN = 4  # rough estimation factor


def _load_wiki_files(wiki_dir: Path, full: bool = True) -> str:
    """Concatenate wiki markdown files into a single string.

    When *full* is True every .md file is included.  When False (fallback mode)
    only AGENTS.md, INDEX files, and concept articles are loaded — individual
    source summaries under sources/ are skipped.
    """
    parts: list[str] = []
    for md_path in sorted(wiki_dir.rglob("*.md")):
        # Always skip the _meta directory (JSON metadata, not content).
        if "_meta" in md_path.relative_to(wiki_dir).parts:
            continue

        if not full:
            rel = md_path.relative_to(wiki_dir)
            in_sources = rel.parts[0] == "sources" if rel.parts else False
            is_index = rel.name.upper() == "INDEX.MD"
            # In fallback mode keep AGENTS.md, any INDEX file, and concepts/.
            if in_sources and not is_index:
                continue

        relative = md_path.relative_to(wiki_dir.parent)
        content = md_path.read_text(encoding="utf-8")
        parts.append(f"=== {relative} ===\n{content}")

    return "\n\n".join(parts)


def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def ask(project_dir: Path, question: str, save: bool = False) -> str:
    """Ask a question against the compiled wiki. Returns the answer."""
    wiki_dir = project_dir / "wiki"
    model = get_model("strong", project_dir)
    context_limit = get_context_limit(model)
    token_budget = int(context_limit * CONTEXT_BUDGET_RATIO)

    # --- 1. Load wiki content (full first, fallback if too large) ----------
    wiki_content = _load_wiki_files(wiki_dir, full=True)

    if _estimate_tokens(wiki_content) > token_budget:
        click.echo(
            "Warning: wiki exceeds 80% of context limit — "
            "falling back to indexes + concepts only.",
            err=True,
        )
        wiki_content = _load_wiki_files(wiki_dir, full=False)

    # --- 2. Read AGENTS.md for the prompt schema section -------------------
    agents_path = wiki_dir / "AGENTS.md"
    agents_md = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""

    # --- 3. Build the prompt -----------------------------------------------
    template_path = Path(__file__).parent / "prompts" / "ask.md"
    template = template_path.read_text(encoding="utf-8")
    prompt = template.format(
        agents_md=agents_md,
        wiki_content=wiki_content,
        question=question,
    )

    # --- 4. Call the LLM ---------------------------------------------------
    client = get_client(project_dir)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = response.choices[0].message.content

    # --- 5. Optionally save as a report ------------------------------------
    if save:
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

        git_add_and_commit(
            project_dir,
            f"wiki: add report — {question[:60]}",
        )

    return answer
