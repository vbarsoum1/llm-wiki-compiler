"""OpenRouter client wrapper and model routing."""

from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_MODELS: dict[str, str] = {
    "fast": "google/gemini-2.5-flash",
    "strong": "anthropic/claude-sonnet-4-6",
}

CONTEXT_LIMITS: dict[str, int] = {
    "google/gemini-2.5-flash": 1_048_576,
    "google/gemini-2.5-pro": 1_048_576,
    "anthropic/claude-sonnet-4-6": 200_000,
    "anthropic/claude-opus-4-6": 200_000,
    "anthropic/claude-haiku-4-5": 200_000,
    "openai/gpt-4o": 128_000,
}

DEFAULT_CONTEXT_LIMIT = 128_000


def _load_config(project_dir: Path) -> dict:
    config_path = project_dir / ".klore" / "config.json"
    if config_path.is_file():
        with open(config_path) as f:
            return json.load(f)
    return {}


def _resolve_api_key(project_dir: Path) -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key

    config = _load_config(project_dir)
    key = config.get("api_key")
    if key:
        return key

    raise RuntimeError(
        "No OpenRouter API key found. "
        "Set the OPENROUTER_API_KEY environment variable or add "
        '"api_key" to .klore/config.json.'
    )


def get_client(project_dir: Path) -> OpenAI:
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=_resolve_api_key(project_dir),
    )


def get_model(tier: str, project_dir: Path) -> str:
    if tier not in DEFAULT_MODELS:
        raise ValueError(f"Unknown model tier {tier!r}. Expected 'fast' or 'strong'.")

    config = _load_config(project_dir)
    model_overrides = config.get("model", {})
    return model_overrides.get(tier, DEFAULT_MODELS[tier])


def get_context_limit(model_id: str) -> int:
    return CONTEXT_LIMITS.get(model_id, DEFAULT_CONTEXT_LIMIT)
