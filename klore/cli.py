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
    (wiki_dir / "entities").mkdir(exist_ok=True)
    (wiki_dir / "reports").mkdir(exist_ok=True)
    (wiki_dir / "_meta").mkdir(exist_ok=True)

    # Create log.md and overview.md if they don't exist
    log_path = wiki_dir / "log.md"
    if not log_path.exists():
        log_path.write_text("# Log\n", encoding="utf-8")
    overview_path = wiki_dir / "overview.md"
    if not overview_path.exists():
        overview_path.write_text(
            "# Overview\n\n*No sources compiled yet.*\n",
            encoding="utf-8",
        )

    # Create .klore/ config dir and copy agents.md template
    config_dir = project_dir / ".klore"
    config_dir.mkdir(exist_ok=True)

    template = Path(__file__).parent / "prompts" / "agents_template.md"
    agents_dest = config_dir / "agents.md"
    if not agents_dest.exists():
        agents_dest.write_text(template.read_text("utf-8"), encoding="utf-8")
    config_path = config_dir / "config.json"
    if not config_path.exists():
        from klore.models import DEFAULT_MODELS

        config_data: dict = {
            "model": dict(DEFAULT_MODELS),
            "api_key": None,
        }

        # Prompt for API key if running interactively
        if sys.stdin.isatty():
            click.echo("")
            key = click.prompt(
                "OpenRouter API key (get one at https://openrouter.ai/keys)\n"
                "  Paste key or press Enter to skip",
                default="",
                show_default=False,
            )
            if key.strip():
                config_data["api_key"] = key.strip()

        config_path.write_text(
            json.dumps(config_data, indent=2) + "\n",
            encoding="utf-8",
        )

    # Initialize git
    from klore.git import git_init

    git_init(project_dir)

    click.echo(f"\nInitialized klore knowledge base at {project_dir}")
    click.echo(f"  raw/          — drop your source files here")
    click.echo(f"  wiki/         — compiled output (Obsidian-compatible)")
    click.echo(f"  wiki/log.md   — chronological record of all operations")
    click.echo(f"  .klore/       — configuration & schema")
    if not config_data.get("api_key"):
        click.echo(f"\n  Set your API key: klore config set api_key sk-or-v1-...")
        click.echo(f"  Get one at: https://openrouter.ai/keys")
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
@click.argument("source")
def ingest(source: str):
    """Add a source and compile in one step."""
    project_dir = _require_project()
    raw_dir = project_dir / "raw"

    from klore.ingester import ingest_file, ingest_url

    # Add the source
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

    # Pre-flight: check API key
    from klore.models import get_client

    try:
        get_client(project_dir)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Compile incrementally
    from klore.compiler import compile_wiki

    click.echo("Compiling...")
    stats = asyncio.run(compile_wiki(project_dir, full=False))

    click.echo(f"\nDone: {stats['sources_processed']} sources, "
               f"{stats['concepts_generated']} concepts, "
               f"{stats.get('entities_created', 0)} entities.")


@cli.command()
@click.option("--full", is_flag=True, help="Force full recompilation.")
@click.option("--topic", default=None, help="Recompile a specific concept only.")
def compile(full: bool, topic: str | None):
    """Compile raw sources into the wiki."""
    project_dir = _require_project()

    # Check for sources (skip check when topic-only compile uses existing summaries)
    if not topic:
        raw_dir = project_dir / "raw"
        sources = list(raw_dir.rglob("*"))
        sources = [s for s in sources if s.is_file()]
        if not sources:
            click.echo("No sources found in raw/. Add some with `klore add`.", err=True)
            sys.exit(1)

    # Pre-flight checks: API key and model validity
    from klore.models import get_client, get_model

    try:
        client = get_client(project_dir)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Validate models with a tiny test call
    for tier in ("fast", "strong", "director"):
        model = get_model(tier, project_dir)
        try:
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "not found" in err_str.lower():
                click.echo(
                    f"Error: {tier} model '{model}' not found on OpenRouter.\n"
                    f"Check available models at https://openrouter.ai/models\n"
                    f"Fix: klore config set model.{tier} <valid-model-id>",
                    err=True,
                )
                sys.exit(1)
            elif "401" in err_str or "auth" in err_str.lower():
                click.echo(
                    f"Error: OpenRouter API key is invalid or expired.\n"
                    f"Get a new key at: https://openrouter.ai/keys",
                    err=True,
                )
                sys.exit(1)
            # Other errors (rate limits, etc.) — let compile handle them
            break

    from klore.compiler import compile_wiki

    stats = asyncio.run(compile_wiki(project_dir, full=full, topic=topic))

    click.echo(f"\nCompilation complete:")
    click.echo(f"  Sources processed:  {stats['sources_processed']}")
    click.echo(f"  Concepts generated: {stats['concepts_generated']}")
    click.echo(f"  Entities created:   {stats.get('entities_created', 0)}")
    click.echo(f"  Tags normalized:    {stats['tags_normalized']}")
    if stats.get("pass1_skipped"):
        click.echo(f"  Sources skipped:    {stats['pass1_skipped']}")
    if stats.get("pass1_errors"):
        click.echo(f"  Errors:             {stats['pass1_errors']}")
    if stats.get("total_tokens"):
        click.echo(f"  Tokens used:        {stats['total_tokens']:,}")


@cli.command()
def watch():
    """Watch raw/ for changes and auto-compile."""
    project_dir = _require_project()
    raw_dir = project_dir / "raw"

    import time

    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class _CompileHandler(FileSystemEventHandler):
        def __init__(self):
            self._pending = False
            self._last_event = 0.0

        def on_any_event(self, event):
            if event.is_directory:
                return
            self._pending = True
            self._last_event = time.time()

    handler = _CompileHandler()
    observer = Observer()
    observer.schedule(handler, str(raw_dir), recursive=True)
    observer.start()

    click.echo(f"Watching {raw_dir} for changes... (Ctrl+C to stop)")

    try:
        while True:
            time.sleep(1)
            # Debounce: compile 2 seconds after last event
            if handler._pending and (time.time() - handler._last_event) >= 2:
                handler._pending = False
                click.echo("\nChange detected, compiling...")
                try:
                    from klore.compiler import compile_wiki

                    stats = asyncio.run(compile_wiki(project_dir, full=False))
                    click.echo(
                        f"Done: {stats['sources_processed']} sources, "
                        f"{stats['concepts_generated']} concepts."
                    )
                except Exception as exc:
                    click.echo(f"Compile error: {exc}", err=True)
                click.echo("Watching for changes...")
    except KeyboardInterrupt:
        observer.stop()
        click.echo("\nStopped.")
    observer.join()


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

    answer = asyncio.run(do_ask(project_dir, question, save=save))
    click.echo(answer)

    if save:
        click.echo("\n(Answer saved to wiki/reports/)", err=True)


@cli.command()
def lint():
    """Run health checks on the compiled wiki."""
    project_dir = _require_project()

    from klore.linter import lint as do_lint

    report = asyncio.run(do_lint(project_dir))
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
    concept_articles = [
        c for c in (wiki_dir / "concepts").glob("*.md")
        if c.name != "INDEX.md"
    ]
    entity_pages = list((wiki_dir / "entities").glob("*.md"))
    reports = list((wiki_dir / "reports").glob("*.md"))

    from klore.state import CompileState

    state = CompileState.load(wiki_dir)

    click.echo(f"Klore Knowledge Base: {project_dir.name}")
    click.echo(f"  Raw sources:       {len(source_files)}")
    click.echo(f"  Source summaries:   {len(source_summaries)}")
    click.echo(f"  Concept articles:   {len(concept_articles)}")
    click.echo(f"  Entity pages:       {len(entity_pages)}")
    click.echo(f"  Reports:            {len(reports)}")
    click.echo(f"  Last compiled:      {state.last_compiled or 'never'}")

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
