"""Document ingestion and format conversion via markitdown."""

from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

from markitdown import MarkItDown


class IngestionError(Exception):
    """Raised when document ingestion or conversion fails."""


def slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"&[a-zA-Z]+;", " ", text)  # strip HTML entities
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return text or "untitled"


def ingest_file(source_path: Path, raw_dir: Path) -> Path:
    """Copy a local file into raw_dir; return the path within raw_dir."""
    source_path = source_path.resolve()
    raw_dir = raw_dir.resolve()

    if source_path.parent == raw_dir or str(source_path).startswith(str(raw_dir) + "/"):
        return source_path

    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / source_path.name

    if dest.exists() and dest.resolve() != source_path:
        stem, suffix = source_path.stem, source_path.suffix
        counter = 1
        while dest.exists():
            dest = raw_dir / f"{stem}-{counter}{suffix}"
            counter += 1

    shutil.copy2(source_path, dest)
    return dest


def ingest_url(url: str, raw_dir: Path) -> Path:
    """Fetch a URL, convert to markdown, and save to raw_dir."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    md = MarkItDown()
    try:
        result = md.convert(url)
    except Exception as exc:
        raise IngestionError(f"Failed to fetch URL {url}: {exc}") from exc

    title = result.title if result.title else url
    filename = f"{slugify(title)}.md"
    dest = raw_dir / filename

    dest.write_text(result.text_content or "", encoding="utf-8")
    return dest


def convert_to_markdown(file_path: Path) -> str:
    """Convert any supported file to markdown text."""
    md = MarkItDown()
    try:
        result = md.convert(str(file_path))
    except Exception as exc:
        raise IngestionError(
            f"Failed to convert {file_path.name}: {exc}"
        ) from exc

    if result.text_content is None:
        raise IngestionError(f"Conversion of {file_path.name} produced no content.")

    return result.text_content


# ── Large document chunking ──────────────────────────────────────────

# Documents above this word count are split into chapters
CHUNK_THRESHOLD = 50_000

# Patterns that indicate chapter/section boundaries in markdown
_CHAPTER_PATTERNS = [
    re.compile(r"^#{1,2}\s+.+", re.MULTILINE),  # # or ## headings
    re.compile(r"^Chapter\s+\d+", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Part\s+\d+", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^CHAPTER\s+[IVXLCDM\d]+", re.MULTILINE),
]


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """Split markdown text by top-level headings.

    Returns list of (heading, content) tuples.
    """
    # Find all heading positions
    heading_re = re.compile(r"^(#{1,2}\s+.+)$", re.MULTILINE)
    matches = list(heading_re.finditer(text))

    if not matches:
        return [("Full Document", text)]

    chunks: list[tuple[str, str]] = []

    # Content before first heading
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            chunks.append(("Preamble", preamble))

    for i, match in enumerate(matches):
        heading = match.group(1).lstrip("#").strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            chunks.append((heading, content))

    return chunks


def chunk_large_document(
    content: str, source_name: str
) -> list[tuple[str, str]] | None:
    """Split a large document into chapter-sized chunks.

    Returns None if the document is small enough to process as-is.
    Returns list of (chunk_name, chunk_content) tuples if chunked.
    """
    word_count = len(content.split())
    if word_count < CHUNK_THRESHOLD:
        return None

    # Try splitting by headings
    chunks = _split_by_headings(content)

    if len(chunks) <= 1:
        # No headings found — split by approximate size
        target_words = 30_000
        words = content.split()
        chunks = []
        for i in range(0, len(words), target_words):
            chunk_num = (i // target_words) + 1
            chunk_words = words[i : i + target_words]
            chunks.append(
                (f"Part {chunk_num}", " ".join(chunk_words))
            )

    # Merge very small chunks (< 1000 words) into the previous one
    merged: list[tuple[str, str]] = []
    for heading, text in chunks:
        if merged and len(text.split()) < 1000:
            prev_heading, prev_text = merged[-1]
            merged[-1] = (prev_heading, prev_text + "\n\n" + text)
        else:
            merged.append((heading, text))

    return merged
