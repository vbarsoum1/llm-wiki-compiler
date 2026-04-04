"""Unit tests for klore/hash.py and klore/state.py."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from klore.hash import hash_file, hash_string
from klore.state import CompileState


# ── hash.py tests ────────────────────────────────────────────────


def test_hash_file(tmp_path: Path) -> None:
    """hash_file returns the correct SHA-256 hex digest for a file."""
    content = b"hello world"
    p = tmp_path / "sample.txt"
    p.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    assert hash_file(p) == expected


def test_hash_string() -> None:
    """hash_string returns the correct SHA-256 hex digest for a string."""
    content = "hello world"
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert hash_string(content) == expected


# ── state.py tests ───────────────────────────────────────────────


def test_load_empty_state(tmp_path: Path) -> None:
    """Loading from a nonexistent file returns an empty CompileState."""
    state = CompileState.load(tmp_path)

    assert state.file_hashes == {}
    assert state.concept_sources == {}
    assert state.entity_sources == {}
    assert state.prompt_hash is None
    assert state.last_compiled is None
    assert state.compilation_count == 0


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """Saving a state and loading it back preserves all fields."""
    state = CompileState()
    state.file_hashes = {"raw/paper.pdf": "abc123", "raw/notes.md": "def456"}
    state.concept_sources = {"quantum": ["paper", "notes"], "gravity": ["paper"]}
    state.entity_sources = {"einstein": ["paper"], "bohr": ["paper", "notes"]}
    state.prompt_hash = "prompt_hash_value"

    state.save(tmp_path)
    loaded = CompileState.load(tmp_path)

    assert loaded.file_hashes == state.file_hashes
    assert loaded.concept_sources == state.concept_sources
    assert loaded.entity_sources == state.entity_sources
    assert loaded.prompt_hash == state.prompt_hash
    assert loaded.last_compiled is not None
    assert loaded.compilation_count == 1


def test_diff_finds_new_files(tmp_path: Path) -> None:
    """Files present on disk but absent from state are reported as new."""
    project = tmp_path / "project"
    raw_dir = project / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "new_file.txt").write_text("new content")

    state = CompileState()
    new, changed, removed = state.diff_sources(raw_dir)

    assert len(new) == 1
    assert new[0] == Path("raw/new_file.txt")
    assert changed == []
    assert removed == []


def test_diff_finds_changed_files(tmp_path: Path) -> None:
    """Files whose hash differs from the stored hash are reported as changed."""
    project = tmp_path / "project"
    raw_dir = project / "raw"
    raw_dir.mkdir(parents=True)
    f = raw_dir / "paper.txt"
    f.write_text("original content")

    state = CompileState()
    state.file_hashes = {"raw/paper.txt": "stale_hash_value"}

    new, changed, removed = state.diff_sources(raw_dir)

    assert new == []
    assert len(changed) == 1
    assert changed[0] == Path("raw/paper.txt")
    assert removed == []


def test_diff_finds_removed_files(tmp_path: Path) -> None:
    """Files in state but absent from disk are reported as removed."""
    project = tmp_path / "project"
    raw_dir = project / "raw"
    raw_dir.mkdir(parents=True)

    state = CompileState()
    state.file_hashes = {"raw/gone.txt": "some_hash"}

    new, changed, removed = state.diff_sources(raw_dir)

    assert new == []
    assert changed == []
    assert len(removed) == 1
    assert removed[0] == Path("raw/gone.txt")


def test_needs_full_recompile() -> None:
    """Returns True when prompt hash differs, False when same."""
    state = CompileState()
    state.prompt_hash = "hash_a"

    assert state.needs_full_recompile("hash_b") is True
    assert state.needs_full_recompile("hash_a") is False


def test_get_affected_concepts() -> None:
    """Returns the correct set of concepts for changed sources."""
    state = CompileState()
    state.concept_sources = {
        "quantum": ["paper1", "paper2"],
        "gravity": ["paper2", "paper3"],
        "optics": ["paper4"],
    }

    affected = state.get_affected_concepts(["paper2"])
    assert affected == {"quantum", "gravity"}

    affected_none = state.get_affected_concepts(["paper99"])
    assert affected_none == set()

    affected_single = state.get_affected_concepts(["paper4"])
    assert affected_single == {"optics"}


def test_get_affected_entities() -> None:
    """Returns the correct set of entities for changed sources."""
    state = CompileState()
    state.entity_sources = {
        "einstein": ["paper1", "paper2"],
        "bohr": ["paper2", "paper3"],
        "feynman": ["paper4"],
    }

    affected = state.get_affected_entities(["paper2"])
    assert affected == {"einstein", "bohr"}

    affected_none = state.get_affected_entities(["paper99"])
    assert affected_none == set()


def test_compilation_count_increments(tmp_path: Path) -> None:
    """Each save increments compilation_count."""
    state = CompileState()
    assert state.compilation_count == 0

    state.save(tmp_path)
    assert state.compilation_count == 1

    state.save(tmp_path)
    assert state.compilation_count == 2
