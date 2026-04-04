"""Unit tests for klore/models.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from klore.models import get_client, get_context_limit, get_model


def test_default_fast_model(tmp_path: Path) -> None:
    """get_model('fast', ...) returns google/gemini-3-flash-preview with no config."""
    assert get_model("fast", tmp_path) == "google/gemini-3-flash-preview"


def test_default_strong_model(tmp_path: Path) -> None:
    """get_model('strong', ...) returns google/gemini-3.1-pro-preview with no config."""
    assert get_model("strong", tmp_path) == "google/gemini-3.1-pro-preview"


def test_default_director_model(tmp_path: Path) -> None:
    """get_model('director', ...) returns anthropic/claude-opus-4.6 with no config."""
    assert get_model("director", tmp_path) == "anthropic/claude-opus-4.6"


def test_config_override_model(tmp_path: Path) -> None:
    """get_model reads model overrides from .klore/config.json."""
    config_dir = tmp_path / ".klore"
    config_dir.mkdir()
    config = {
        "model": {
            "fast": "openai/gpt-4o-mini",
            "strong": "anthropic/claude-sonnet-4-6",
            "director": "anthropic/claude-opus-4-6",
        }
    }
    (config_dir / "config.json").write_text(json.dumps(config))

    assert get_model("fast", tmp_path) == "openai/gpt-4o-mini"
    assert get_model("strong", tmp_path) == "anthropic/claude-sonnet-4-6"
    assert get_model("director", tmp_path) == "anthropic/claude-opus-4-6"


def test_invalid_tier_raises(tmp_path: Path) -> None:
    """get_model raises ValueError for an unknown tier."""
    with pytest.raises(ValueError, match="Unknown model tier"):
        get_model("unknown", tmp_path)


def test_context_limit_known_model() -> None:
    """Known models return their correct context limits."""
    assert get_context_limit("google/gemini-3-flash-preview") == 1_048_576
    assert get_context_limit("google/gemini-3.1-pro-preview") == 1_048_576
    assert get_context_limit("anthropic/claude-opus-4.6") == 1_000_000
    assert get_context_limit("anthropic/claude-sonnet-4-6") == 200_000
    assert get_context_limit("openai/gpt-4o") == 128_000


def test_context_limit_unknown_model() -> None:
    """Unknown models fall back to the 128000 default."""
    assert get_context_limit("some/unknown-model") == 128_000


def test_missing_api_key_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_client raises RuntimeError when no API key is available."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Prevent dotenv from loading .env.local files
    monkeypatch.setattr("klore.models.load_dotenv", lambda *a, **kw: None)

    with pytest.raises(RuntimeError, match="No OpenRouter API key found"):
        get_client(tmp_path)
