"""Klore CLI — LLM Knowledge Compiler."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from klore import __version__


def _project_dir() -> Path:
    """Find the project root (directory containing .klore/)."""
    cwd = Path.cwd()
    # Walk up looking for .klore/
    for parent in [cwd, *cwd.parents]:
        if (parent / ".klore").is_dir():
            return parent
    # Fall back to cwd if no .klore/ found
    return cwd


def _require_project() -> Path:
    """Return project dir or exit with error if not initialized."""
    d = _project_dir()
    if not (d / ".klore").is_dir():
        click.echo("Error: not a klore project. Run `klore init` first.", err=True)
        sys.exit(1)
    return d


@click.group()
@click.version_option(__version__)
def cli():
    """Klore — LLM Knowledge Compiler.

    Raw sources in, living knowledge base out.
    """


@cli.command()
@click.argument("name", default=".")
def init(name: str):
    """Create a new klore knowledge base."""
    project_dir = Path(name).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    # Create directory structure
    (project_dir / "raw").mkdir(exist_ok=True)
    wiki_dir = project_dir / "wiki"
    wiki_dir.mkdir(exist_ok=True)
    (wiki_dir / "sources").mkdir(exist_ok=True)
    (wiki_dir / "concepts").mkdir(exist_ok=True)
    (wiki_dir / "reports").mkdir(exist_ok=True)
    (wiki_dir / "_meta").mkdir(exist_ok=True)

    # Copy AGENTS.md template
    template = Path(__file__).parent / "prompts" / "agents_template.md"
    agents_dest = wiki_dir / "AGENTS.md"
    if not agents_dest.exists():
        agents_dest.write_text(template.read_text("utf-8"), encoding="utf-8")

    # Create default config
    config_dir = project_dir / ".klore"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(
            json.dumps(
                {
                    "model": {
                        "fast": "google/gemini-2.5-flash",
                        "strong": "anthropic/claude-sonnet-4-6",
                    },
                    "api_key": None,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    # Initialize git
    from klore.git import git_init

    git_init(project_dir)

    click.echo(f"Initialized klore knowledge base at {project_dir}")
    click.echo(f"  raw/          — drop your source files here")
    click.echo(f"  wiki/         — compiled output (Obsidian-compatible)")
    click.echo(f"  .klore/       — configuration")
    click.echo(f"\nNext: klore add <file-or-url>, then klore compile")


@cli.command()
@click.argument("source")
def add(source: str):
    """Add a source file or URL to the knowledge base."""
    project_dir = _require_project()
    raw_dir = project_dir / "raw"

    from klore.ingester import ingest_file, ingest_url

    if source.startswith("http://") or source.startswith("https://"):
        path = ingest_url(source, raw_dir)
        click.echo(f"Added URL → {path.relative_to(project_dir)}")
    else:
        source_path = Path(source).resolve()
        if not source_path.exists():
            click.echo(f"Error: {source} not found.", err=True)
            sys.exit(1)
        path = ingest_file(source_path, raw_dir)
        click.echo(f"Added {source_path.name} → {path.relative_to(project_dir)}")


@cli.command()
@click.option("--full", is_flag=True, help="Force full recompilation.")
def compile(full: bool):
    """Compile raw sources into the wiki."""
    project_dir = _require_project()

    # Check for sources
    raw_dir = project_dir / "raw"
    sources = list(raw_dir.rglob("*"))
    sources = [s for s in sources if s.is_file()]
    if not sources:
        click.echo("No sources found in raw/. Add some with `klore add`.", err=True)
        sys.exit(1)

    from klore.compiler import compile_wiki

    stats = asyncio.run(compile_wiki(project_dir, full=full))

    click.echo(f"\nCompilation complete:")
    click.echo(f"  Sources processed: {stats['sources_processed']}")
    click.echo(f"  Concepts generated: {stats['concepts_generated']}")
    click.echo(f"  Tags normalized: {stats['tags_normalized']}")
    if stats.get("pass1_skipped"):
        click.echo(f"  Sources skipped (unchanged): {stats['pass1_skipped']}")
    if stats.get("pass1_errors"):
        click.echo(f"  Sources with errors: {stats['pass1_errors']}")


@cli.command()
@click.argument("question")
@click.option("--save", is_flag=True, help="Save the answer to wiki/reports/.")
def ask(question: str, save: bool):
    """Ask a question against the compiled wiki."""
    project_dir = _require_project()

    wiki_dir = project_dir / "wiki"
    if not any(wiki_dir.rglob("*.md")):
        click.echo("No compiled wiki found. Run `klore compile` first.", err=True)
        sys.exit(1)

    from klore.asker import ask as do_ask

    answer = do_ask(project_dir, question, save=save)
    click.echo(answer)

    if save:
        click.echo("\n(Answer saved to wiki/reports/)", err=True)


@cli.command()
def lint():
    """Run health checks on the compiled wiki."""
    project_dir = _require_project()

    from klore.linter import lint as do_lint

    report = do_lint(project_dir)
    click.echo(report)


@cli.command()
@click.option("--since", default=None, help="Time range, e.g. '2w', '7d', '1m'.")
def diff(since: str | None):
    """Show what changed in the wiki."""
    project_dir = _require_project()

    from klore.git import git_diff

    output = git_diff(project_dir, since=since)
    if output:
        click.echo(output)
    else:
        click.echo("No changes found.")


@cli.command()
def status():
    """Show compilation state and source counts."""
    project_dir = _require_project()
    raw_dir = project_dir / "raw"
    wiki_dir = project_dir / "wiki"

    source_files = [f for f in raw_dir.rglob("*") if f.is_file()]
    source_summaries = list((wiki_dir / "sources").glob("*.md"))
    concept_articles = list((wiki_dir / "concepts").glob("*.md"))
    concept_articles = [c for c in concept_articles if c.name != "INDEX.md"]
    reports = list((wiki_dir / "reports").glob("*.md"))

    from klore.state import CompileState

    state = CompileState.load(wiki_dir)

    click.echo(f"Klore Knowledge Base: {project_dir.name}")
    click.echo(f"  Raw sources:      {len(source_files)}")
    click.echo(f"  Source summaries:  {len(source_summaries)}")
    click.echo(f"  Concept articles:  {len(concept_articles)}")
    click.echo(f"  Reports:          {len(reports)}")
    click.echo(f"  Last compiled:    {state.last_compiled or 'never'}")

    # Check for uncompiled sources
    if state.file_hashes:
        new, changed, removed = state.diff_sources(raw_dir)
        if new or changed or removed:
            click.echo(f"\n  Pending changes:")
            if new:
                click.echo(f"    New:     {len(new)} sources")
            if changed:
                click.echo(f"    Changed: {len(changed)} sources")
            if removed:
                click.echo(f"    Removed: {len(removed)} sources")
            click.echo(f"  Run `klore compile` to update the wiki.")
        else:
            click.echo(f"\n  Wiki is up to date.")


@cli.command("config")
@click.argument("action", type=click.Choice(["set", "get"]))
@click.argument("key")
@click.argument("value", required=False)
def config_cmd(action: str, key: str, value: str | None):
    """Get or set configuration values."""
    project_dir = _require_project()
    config_path = project_dir / ".klore" / "config.json"

    if config_path.exists():
        config = json.loads(config_path.read_text("utf-8"))
    else:
        config = {}

    # Support dot notation: model.fast → config["model"]["fast"]
    parts = key.split(".")

    if action == "get":
        obj = config
        for p in parts:
            if isinstance(obj, dict):
                obj = obj.get(p)
            else:
                obj = None
                break
        click.echo(obj if obj is not None else f"Key '{key}' not found.")

    elif action == "set":
        if value is None:
            click.echo("Error: value required for 'set'.", err=True)
            sys.exit(1)
        obj = config
        for p in parts[:-1]:
            obj = obj.setdefault(p, {})
        obj[parts[-1]] = value
        config_path.write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
        click.echo(f"Set {key} = {value}")
