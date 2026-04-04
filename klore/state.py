"""Compilation state tracking for incremental builds.

Manages wiki/_meta/compile-state.json so klore only recompiles what changed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from klore.hash import hash_file

STATE_FILENAME = "compile-state.json"
META_DIR = "_meta"


class CompileState:
    """Tracks file hashes, concept-source mappings, entity mappings, and prompt hash."""

    def __init__(self) -> None:
        self.file_hashes: dict[str, str] = {}
        self.concept_sources: dict[str, list[str]] = {}
        self.entity_sources: dict[str, list[str]] = {}
        self.prompt_hash: str | None = None
        self.last_compiled: str | None = None
        self.compilation_count: int = 0

    # ── Persistence ──────────────────────────────────────────────

    @classmethod
    def load(cls, wiki_dir: Path) -> CompileState:
        """Load state from disk. Returns empty state if file not found."""
        path = wiki_dir / META_DIR / STATE_FILENAME
        state = cls()
        if path.exists():
            data = json.loads(path.read_text("utf-8"))
            state.file_hashes = data.get("file_hashes", {})
            state.concept_sources = data.get("concept_sources", {})
            state.entity_sources = data.get("entity_sources", {})
            state.prompt_hash = data.get("prompt_hash")
            state.last_compiled = data.get("last_compiled")
            state.compilation_count = data.get("compilation_count", 0)
        return state

    def save(self, wiki_dir: Path) -> None:
        """Write state to disk, creating _meta directory if needed."""
        meta = wiki_dir / META_DIR
        meta.mkdir(parents=True, exist_ok=True)
        self.last_compiled = datetime.now(timezone.utc).isoformat()
        self.compilation_count += 1
        data = {
            "file_hashes": self.file_hashes,
            "concept_sources": self.concept_sources,
            "entity_sources": self.entity_sources,
            "prompt_hash": self.prompt_hash,
            "last_compiled": self.last_compiled,
            "compilation_count": self.compilation_count,
        }
        (meta / STATE_FILENAME).write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    # ── Diffing ──────────────────────────────────────────────────

    def diff_sources(
        self, raw_dir: Path
    ) -> tuple[list[Path], list[Path], list[Path]]:
        """Compare current files against stored hashes.

        Returns (new, changed, removed) as lists of Paths relative to the
        project root (e.g. ``raw/paper1.pdf``).
        """
        current: dict[str, str] = {}
        for p in raw_dir.rglob("*"):
            if p.is_dir():
                continue
            # Store paths relative to the project root (raw_dir's parent).
            rel = str(p.relative_to(raw_dir.parent))
            current[rel] = hash_file(p)

        stored_keys = set(self.file_hashes)
        current_keys = set(current)

        new = sorted(Path(k) for k in current_keys - stored_keys)
        removed = sorted(Path(k) for k in stored_keys - current_keys)
        changed = sorted(
            Path(k)
            for k in current_keys & stored_keys
            if current[k] != self.file_hashes[k]
        )

        return new, changed, removed

    # ── Prompt hash ──────────────────────────────────────────────

    def needs_full_recompile(self, prompt_hash: str) -> bool:
        """True if the given prompt hash differs from the stored one."""
        return self.prompt_hash != prompt_hash

    def set_prompt_hash(self, hash: str) -> None:
        """Update the stored prompt hash."""
        self.prompt_hash = hash

    # ── Hash updates ─────────────────────────────────────────────

    def update_hash(self, rel_path: str, hash: str) -> None:
        """Update (or add) the hash for a single file."""
        self.file_hashes[rel_path] = hash

    # ── Concept-source mapping ───────────────────────────────────

    def update_concept_sources(
        self, concept_slug: str, source_slugs: list[str]
    ) -> None:
        """Update which sources contribute to a concept."""
        self.concept_sources[concept_slug] = source_slugs

    def get_affected_concepts(self, changed_sources: list[str]) -> set[str]:
        """Given changed source slugs, return concepts that need regeneration."""
        changed = set(changed_sources)
        return {
            concept
            for concept, sources in self.concept_sources.items()
            if changed & set(sources)
        }

    # ── Entity-source mapping ────────────────────────────────────

    def update_entity_sources(
        self, entity_slug: str, source_slugs: list[str]
    ) -> None:
        """Update which sources contribute to an entity."""
        self.entity_sources[entity_slug] = source_slugs

    def get_affected_entities(self, changed_sources: list[str]) -> set[str]:
        """Given changed source slugs, return entities that need regeneration."""
        changed = set(changed_sources)
        return {
            entity
            for entity, sources in self.entity_sources.items()
            if changed & set(sources)
        }
