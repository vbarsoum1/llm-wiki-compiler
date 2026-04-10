"""Tests for CLI commands: status, config, add, diff."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from klore.cli import cli


@pytest.fixture()
def klore_project(tmp_path: Path) -> Path:
    """Create a fully initialized Klore project."""
    runner = CliRunner()
    project_dir = tmp_path / "test-kb"
    result = runner.invoke(cli, ["init", str(project_dir)])
    assert result.exit_code == 0
    return project_dir


class TestStatus:

    def test_status_shows_counts(self, klore_project: Path):
        # Add a raw source
        (klore_project / "raw" / "paper.md").write_text("# Paper\nContent.")
        (klore_project / "wiki" / "sources" / "paper.md").write_text("# Summary")
        (klore_project / "wiki" / "concepts" / "ml.md").write_text("# ML")

        runner = CliRunner()
        with patch("klore.cli._project_dir", return_value=klore_project):
            result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Raw sources:" in result.output
        assert "Source summaries:" in result.output
        assert "Concept articles:" in result.output

    def test_status_shows_pending_changes(self, klore_project: Path):
        # Add a raw source and fake state with old hash
        (klore_project / "raw" / "paper.md").write_text("content")
        state = {
            "file_hashes": {"raw/paper.md": "old_hash"},
            "concept_sources": {},
            "entity_sources": {},
            "prompt_hash": None,
            "last_compiled": "2026-04-01",
            "compilation_count": 1,
            "total_tokens_used": 0,
        }
        meta = klore_project / "wiki" / "_meta"
        meta.mkdir(exist_ok=True)
        (meta / "compile-state.json").write_text(json.dumps(state))

        runner = CliRunner()
        with patch("klore.cli._project_dir", return_value=klore_project):
            result = runner.invoke(cli, ["status"])

        assert "Changed:" in result.output or "Pending" in result.output


class TestConfig:

    def test_config_get(self, klore_project: Path):
        runner = CliRunner()
        with patch("klore.cli._project_dir", return_value=klore_project):
            result = runner.invoke(cli, ["config", "get", "model.fast"])

        assert result.exit_code == 0
        assert "gemini" in result.output

    def test_config_set(self, klore_project: Path):
        runner = CliRunner()
        with patch("klore.cli._project_dir", return_value=klore_project):
            result = runner.invoke(
                cli, ["config", "set", "model.fast", "new-model"]
            )

        assert result.exit_code == 0
        assert "Set model.fast = new-model" in result.output

        # Verify it persisted
        config = json.loads(
            (klore_project / ".klore" / "config.json").read_text("utf-8")
        )
        assert config["model"]["fast"] == "new-model"

    def test_config_get_missing_key(self, klore_project: Path):
        runner = CliRunner()
        with patch("klore.cli._project_dir", return_value=klore_project):
            result = runner.invoke(cli, ["config", "get", "nonexistent"])

        assert "not found" in result.output

    def test_config_set_requires_value(self, klore_project: Path):
        runner = CliRunner()
        with patch("klore.cli._project_dir", return_value=klore_project):
            result = runner.invoke(cli, ["config", "set", "model.fast"])

        assert result.exit_code != 0


class TestAdd:

    def test_add_local_file(self, klore_project: Path):
        # Create a source file outside the project
        source = klore_project.parent / "external-paper.md"
        source.write_text("# External Paper\nContent here.")

        runner = CliRunner()
        with patch("klore.cli._project_dir", return_value=klore_project):
            result = runner.invoke(cli, ["add", str(source)])

        assert result.exit_code == 0
        assert "Added" in result.output
        assert (klore_project / "raw" / "external-paper.md").is_file()

    def test_add_nonexistent_file_errors(self, klore_project: Path):
        runner = CliRunner()
        with patch("klore.cli._project_dir", return_value=klore_project):
            result = runner.invoke(cli, ["add", "/tmp/does-not-exist.pdf"])

        assert result.exit_code != 0

    def test_add_url(self, klore_project: Path):
        from unittest.mock import MagicMock

        mock_result = MagicMock()
        mock_result.title = "Web Article"
        mock_result.text_content = "# Web Article\nContent."

        runner = CliRunner()
        with (
            patch("klore.cli._project_dir", return_value=klore_project),
            patch("klore.ingester.MarkItDown") as MockMD,
        ):
            MockMD.return_value.convert.return_value = mock_result
            result = runner.invoke(cli, ["add", "https://example.com/article"])

        assert result.exit_code == 0
        assert "Added URL" in result.output


class TestGit:

    def test_diff_no_changes(self, klore_project: Path):
        import subprocess

        # Need at least one commit for `git diff HEAD` to work
        subprocess.run(
            ["git", "add", "."], cwd=klore_project, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=klore_project, capture_output=True
        )

        runner = CliRunner()
        with patch("klore.cli._project_dir", return_value=klore_project):
            result = runner.invoke(cli, ["diff"])

        assert result.exit_code == 0

    def test_diff_before_first_commit_is_empty(self, klore_project: Path):
        runner = CliRunner()
        with patch("klore.cli._project_dir", return_value=klore_project):
            result = runner.invoke(cli, ["diff"])

        assert result.exit_code == 0
        assert "No changes found." in result.output


class TestLongformCommand:

    def test_longform_command_is_registered(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "longform" in result.output


class TestPlugin:
    """Tests that the Claude Code plugin structure is valid."""

    def test_plugin_json_exists(self):
        plugin_json = Path(__file__).parent.parent / "klore" / "plugin" / "plugins" / "klore" / ".claude-plugin" / "plugin.json"
        assert plugin_json.is_file()
        data = json.loads(plugin_json.read_text("utf-8"))
        assert data["name"] == "klore"
        assert "version" in data

    def test_marketplace_json_exists(self):
        marketplace = Path(__file__).parent.parent / "klore" / "plugin" / ".claude-plugin" / "marketplace.json"
        assert marketplace.is_file()
        data = json.loads(marketplace.read_text("utf-8"))
        assert data["name"] == "klore"
        assert len(data["plugins"]) >= 1

    def test_command_files_are_markdown(self):
        commands_dir = (
            Path(__file__).parent.parent / "klore" / "plugin"
            / "plugins" / "klore" / "commands"
        )
        md_files = list(commands_dir.glob("*.md"))
        assert len(md_files) >= 7  # 7 wiki-* commands

        for md in md_files:
            content = md.read_text("utf-8")
            assert content.startswith("---"), f"{md.name} missing frontmatter"
            assert "description:" in content, f"{md.name} missing description"

    def test_hooks_json_exists(self):
        hooks = (
            Path(__file__).parent.parent / "klore" / "plugin"
            / "plugins" / "klore" / "hooks" / "hooks.json"
        )
        assert hooks.is_file()
        data = json.loads(hooks.read_text("utf-8"))
        assert "hooks" in data
        assert "SessionStart" in data["hooks"]

    def test_session_start_hook_executable(self):
        hook = (
            Path(__file__).parent.parent / "klore" / "plugin"
            / "plugins" / "klore" / "hooks" / "session-start.sh"
        )
        assert hook.is_file()
        import os
        assert os.access(hook, os.X_OK)
