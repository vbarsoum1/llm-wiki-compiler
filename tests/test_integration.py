"""Integration tests for the full Klore init -> add -> compile -> ask loop.

Mocks all LLM calls via klore.models.get_client so no real API key is needed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from klore.cli import cli
from klore.compiler import compile_wiki


# ── Canned LLM Responses ───────────────────────────────────────────

SOURCE_SUMMARY_RESPONSE = """\
---
title: "Test Paper"
source: "raw/test-paper.md"
date: "2026-04-02"
author: "Test Author"
tags: ["machine-learning", "transformers"]
---

# Test Paper

**Source:** [[raw/test-paper.md]]

## Summary

This is a test paper about machine learning and transformers.

## Key Claims

- **Claim 1**: Transformers outperform RNNs on sequence tasks.
  *Provenance: Section 3.1*

## Related Concepts

- [[machine-learning]] — core topic
- [[transformers]] — architecture discussed
"""

TAG_NORMALIZATION_RESPONSE = json.dumps(
    {
        "machine-learning": "machine-learning",
        "transformers": "transformers",
        "ml": "machine-learning",
    }
)

CONCEPT_ARTICLE_RESPONSE = """\
---
title: "Machine Learning"
tags: ["machine-learning"]
sources: ["test-paper"]
---

# Machine Learning

## Definition

Machine learning is a subset of AI focused on learning from data.

## Evidence

According to [[test-paper]], transformers outperform RNNs.

## Sources

- [[test-paper]] — discusses ML approaches
"""

INDEX_RESPONSE = """\
# Knowledge Base Index

*1 sources, 1 concepts. Last compiled: 2026-04-02*

## Concepts

### Machine Learning
- [[machine-learning]] — ML fundamentals

## Sources

- [[test-paper]] — Test Paper (2026-04-02)
"""

ASK_RESPONSE = (
    "Based on the wiki, [[test-paper]] discusses how transformers outperform "
    "RNNs on sequence tasks. The key finding from [[machine-learning]] is "
    "that data-driven approaches are superior."
)

# Second source for incremental compile tests
SOURCE_SUMMARY_RESPONSE_2 = """\
---
title: "Second Paper"
source: "raw/second-paper.md"
date: "2026-04-02"
author: "Another Author"
tags: ["machine-learning", "optimization"]
---

# Second Paper

**Source:** [[raw/second-paper.md]]

## Summary

This is a second paper about optimization in machine learning.

## Key Claims

- **Claim 1**: Adam optimizer converges faster than SGD.
  *Provenance: Section 2.2*

## Related Concepts

- [[machine-learning]] — core topic
- [[optimization]] — optimizer comparison
"""


# ── Mock Factory ────────────────────────────────────────────────────


def _make_mock_client(responses_by_keyword: dict[str, str]) -> MagicMock:
    """Build a mock OpenAI client that returns canned responses by keyword.

    The mock inspects *all* messages in the chat completion request and
    selects the first matching keyword found in the concatenated content.
    """
    mock_client = MagicMock()
    call_log: list[str] = []

    def fake_create(**kwargs):
        # Concatenate all message content for keyword matching
        content = " ".join(
            msg.get("content", "") for msg in kwargs.get("messages", [])
        )
        call_log.append(content)

        for keyword, response in responses_by_keyword.items():
            if keyword.lower() in content.lower():
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = response
                return mock_response

        # Default fallback
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Default response"
        return mock_response

    mock_client.chat.completions.create = fake_create
    mock_client._call_log = call_log
    return mock_client


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def klore_project(tmp_path: Path) -> Path:
    """Create a fully initialized Klore project in a temp directory."""
    runner = CliRunner()
    project_dir = tmp_path / "test-kb"
    result = runner.invoke(cli, ["init", str(project_dir)])
    assert result.exit_code == 0, f"init failed: {result.output}"
    return project_dir


@pytest.fixture()
def mock_client() -> MagicMock:
    """Return a mock OpenAI client wired with standard canned responses.

    Keyword matching order matters: more specific keywords first so that
    the correct response is selected when prompts contain multiple keywords.
    """
    # Order: most-specific keyword first
    responses = {
        "Source Document": SOURCE_SUMMARY_RESPONSE,
        "compile_source": SOURCE_SUMMARY_RESPONSE,
        "normalize": TAG_NORMALIZATION_RESPONSE,
        "tag normalizer": TAG_NORMALIZATION_RESPONSE,
        "Concept Synthesis": CONCEPT_ARTICLE_RESPONSE,
        "concept article": CONCEPT_ARTICLE_RESPONSE,
        "index": INDEX_RESPONSE,
        "Question": ASK_RESPONSE,
        "Answer": ASK_RESPONSE,
    }
    return _make_mock_client(responses)


@pytest.fixture()
def compiled_project(
    klore_project: Path, mock_client: MagicMock
) -> tuple[Path, MagicMock]:
    """Return a Klore project that has already been compiled once."""
    # Write a source file
    raw_dir = klore_project / "raw"
    (raw_dir / "test-paper.md").write_text(
        "# Test Paper\n\nTransformers outperform RNNs on sequence tasks.\n",
        encoding="utf-8",
    )

    with (
        patch("klore.compiler.get_client", return_value=mock_client),
        patch("klore.compiler.get_model", return_value="test-model"),
        patch("klore.compiler.git_add_and_commit"),
        patch("klore.compiler.convert_to_markdown", side_effect=_fake_convert),
    ):
        asyncio.run(compile_wiki(klore_project))

    return klore_project, mock_client


def _fake_convert(file_path: Path) -> str:
    """Read a file as-is instead of going through markitdown."""
    return file_path.read_text(encoding="utf-8")


# ── Tests ───────────────────────────────────────────────────────────


class TestInit:
    """Tests for `klore init`."""

    def test_init_creates_structure(self, tmp_path: Path) -> None:
        """klore init creates all expected directories and config files."""
        runner = CliRunner()
        project_dir = tmp_path / "my-kb"
        result = runner.invoke(cli, ["init", str(project_dir)])

        assert result.exit_code == 0, f"init failed: {result.output}"

        # Directories
        assert (project_dir / "raw").is_dir()
        assert (project_dir / "wiki").is_dir()
        assert (project_dir / "wiki" / "sources").is_dir()
        assert (project_dir / "wiki" / "concepts").is_dir()
        assert (project_dir / "wiki" / "reports").is_dir()
        assert (project_dir / "wiki" / "_meta").is_dir()

        # Config
        assert (project_dir / ".klore" / "config.json").is_file()
        config = json.loads(
            (project_dir / ".klore" / "config.json").read_text("utf-8")
        )
        assert "model" in config
        assert "fast" in config["model"]
        assert "strong" in config["model"]

        # agents.md schema
        assert (project_dir / ".klore" / "agents.md").is_file()

        # Git repository
        assert (project_dir / ".git").is_dir()


class TestFullCompile:
    """Tests for the three-pass compile pipeline."""

    def test_full_compile_loop(
        self, klore_project: Path, mock_client: MagicMock
    ) -> None:
        """A full compile produces sources, concepts, index, and state files."""
        raw_dir = klore_project / "raw"
        wiki_dir = klore_project / "wiki"

        # Write a source file
        (raw_dir / "test-paper.md").write_text(
            "# Test Paper\n\nTransformers outperform RNNs on sequence tasks.\n",
            encoding="utf-8",
        )

        with (
            patch("klore.compiler.get_client", return_value=mock_client),
            patch("klore.compiler.get_model", return_value="test-model"),
            patch("klore.compiler.git_add_and_commit"),
            patch(
                "klore.compiler.convert_to_markdown",
                side_effect=_fake_convert,
            ),
        ):
            stats = asyncio.run(compile_wiki(klore_project))

        # Pass 1: source summary written
        source_files = list((wiki_dir / "sources").glob("*.md"))
        assert len(source_files) >= 1, "Expected at least one source summary"

        # Pass 3: INDEX.md generated
        assert (wiki_dir / "INDEX.md").is_file()

        # State persisted
        state_path = wiki_dir / "_meta" / "compile-state.json"
        assert state_path.is_file()
        state_data = json.loads(state_path.read_text("utf-8"))
        assert "file_hashes" in state_data
        assert len(state_data["file_hashes"]) >= 1

        # Tag aliases persisted
        tag_aliases_path = wiki_dir / "_meta" / "tag-aliases.json"
        assert tag_aliases_path.is_file()
        aliases = json.loads(tag_aliases_path.read_text("utf-8"))
        assert isinstance(aliases, dict)

        # Stats make sense
        assert stats["sources_processed"] >= 1

    def test_compile_writes_valid_source_frontmatter(
        self, compiled_project: tuple[Path, MagicMock]
    ) -> None:
        """Source summaries contain valid YAML frontmatter with required fields."""
        project_dir, _ = compiled_project
        wiki_dir = project_dir / "wiki"

        import yaml

        for md_file in (wiki_dir / "sources").glob("*.md"):
            content = md_file.read_text("utf-8")
            parts = content.split("---", 2)
            assert len(parts) >= 3, f"{md_file.name} missing frontmatter"
            fm = yaml.safe_load(parts[1])
            assert "title" in fm, f"{md_file.name} missing title"
            assert "tags" in fm, f"{md_file.name} missing tags"
            assert isinstance(fm["tags"], list)


class TestIncrementalCompile:
    """Tests for incremental (non-full) compilation."""

    def test_incremental_compile_processes_only_new_file(
        self, compiled_project: tuple[Path, MagicMock]
    ) -> None:
        """Adding a second source and recompiling only processes the new file."""
        project_dir, _ = compiled_project
        raw_dir = project_dir / "raw"

        # Record how many LLM calls the first compile used
        # (we need a fresh mock to count calls for the second compile)
        fresh_client = _make_mock_client(
            {
                "Source Document": SOURCE_SUMMARY_RESPONSE_2,
                "compile_source": SOURCE_SUMMARY_RESPONSE_2,
                "normalize": TAG_NORMALIZATION_RESPONSE,
                "tag normalizer": TAG_NORMALIZATION_RESPONSE,
                "Concept Synthesis": CONCEPT_ARTICLE_RESPONSE,
                "concept article": CONCEPT_ARTICLE_RESPONSE,
                "index": INDEX_RESPONSE,
            }
        )

        # Add a second raw file
        (raw_dir / "second-paper.md").write_text(
            "# Second Paper\n\nAdam optimizer converges faster than SGD.\n",
            encoding="utf-8",
        )

        with (
            patch("klore.compiler.get_client", return_value=fresh_client),
            patch("klore.compiler.get_model", return_value="test-model"),
            patch("klore.compiler.git_add_and_commit"),
            patch(
                "klore.compiler.convert_to_markdown",
                side_effect=_fake_convert,
            ),
        ):
            stats = asyncio.run(compile_wiki(project_dir, full=False))

        # Only the new file should have been processed in Pass 1
        assert stats["sources_processed"] == 1

        # The call log should contain exactly one Pass-1 call (the new file).
        # Pass-1 calls contain "Source Document" in the prompt.
        pass1_calls = [
            c for c in fresh_client._call_log if "Source Document" in c
        ]
        assert len(pass1_calls) == 1, (
            f"Expected 1 Pass-1 LLM call for incremental compile, "
            f"got {len(pass1_calls)}"
        )


class TestAsk:
    """Tests for the ask / Q&A module."""

    def test_ask_returns_answer_with_wikilinks(
        self, compiled_project: tuple[Path, MagicMock]
    ) -> None:
        """ask() returns an answer containing [[wikilinks]]."""
        project_dir, _ = compiled_project

        ask_client = _make_mock_client(
            {
                "Question": ASK_RESPONSE,
                "Answer": ASK_RESPONSE,
            }
        )

        from klore.asker import ask

        with (
            patch("klore.asker.get_client", return_value=ask_client),
            patch("klore.asker.get_model", return_value="test-model"),
            patch(
                "klore.asker.get_context_limit", return_value=200_000
            ),
        ):
            answer = ask(project_dir, "What do transformers do?")

        assert answer is not None
        assert len(answer) > 0
        # Must contain at least one [[wikilink]]
        assert "[[" in answer and "]]" in answer
        assert "[[test-paper]]" in answer

    def test_ask_save_creates_report(
        self, compiled_project: tuple[Path, MagicMock]
    ) -> None:
        """ask(save=True) persists a report file under wiki/reports/."""
        project_dir, _ = compiled_project

        ask_client = _make_mock_client(
            {
                "Question": ASK_RESPONSE,
                "Answer": ASK_RESPONSE,
            }
        )

        from klore.asker import ask

        with (
            patch("klore.asker.get_client", return_value=ask_client),
            patch("klore.asker.get_model", return_value="test-model"),
            patch(
                "klore.asker.get_context_limit", return_value=200_000
            ),
            patch("klore.asker.git_add_and_commit"),
        ):
            ask(project_dir, "What do transformers do?", save=True)

        reports = list((project_dir / "wiki" / "reports").glob("*.md"))
        assert len(reports) >= 1, "Expected at least one saved report"

        # Report should contain frontmatter
        content = reports[0].read_text("utf-8")
        assert content.startswith("---")
        assert "title:" in content
