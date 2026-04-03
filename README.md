<p align="center">
  <img src="klore-readme-banner.png" alt="Klore — LLM Knowledge Compiler" width="100%">
</p>

# Klore — LLM Knowledge Compiler

**Raw sources in, living knowledge base out.**

Drop PDFs, articles, and images into a folder. Klore compiles them into a structured, interlinked Obsidian-compatible wiki — then answers your questions using the compiled knowledge, not retrieved fragments.

**The thesis:** RAG retrieves fragments. Klore compiles knowledge. With 1M+ token context windows, the compiled wiki IS the index.

## Getting Started

### 1. Install

```bash
# Clone the repo
git clone https://github.com/vbarsoum1/klore.git
cd klore

# Create a virtual environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Get an API key

Klore uses [OpenRouter](https://openrouter.ai) for LLM access. Get a free API key at https://openrouter.ai/keys, then:

```bash
export OPENROUTER_API_KEY="sk-or-v1-your-key-here"
```

### 3. Create a knowledge base

```bash
klore init my-research
cd my-research
```

This creates the directory structure: `raw/` for your sources, `wiki/` for the compiled output, and `.klore/` for config.

### 4. Add sources

Add any mix of local files and URLs:

```bash
# Local files (PDF, markdown, HTML, images, DOCX, etc.)
klore add ~/papers/attention-is-all-you-need.pdf
klore add ~/notes/research-notes.md

# URLs (articles, blog posts, web pages)
klore add https://en.wikipedia.org/wiki/Transformer_(deep_learning_model)
```

Check what you've added:
```bash
klore status
```

### 5. Compile the wiki

```bash
klore compile
```

This runs the three-pass compiler: source extraction, tag normalization, concept synthesis, and index generation. You'll see progress output for each pass.

### 6. Browse the wiki

Open the `wiki/` folder in [Obsidian](https://obsidian.md/) as a vault. You'll see:
- `wiki/sources/` — one summary per source with key claims and provenance
- `wiki/concepts/` — synthesized concept articles linking multiple sources
- `wiki/INDEX.md` — master index of everything
- Graph view shows all the cross-links between concepts and sources

Or just read the markdown files directly — they're plain `.md`.

### 7. Ask questions

```bash
klore ask "What are the key findings across these sources?"
```

The answer cites specific sources using `[[wikilinks]]`. Save an answer to the wiki:

```bash
klore ask --save "Compare the approaches described in these papers"
```

### 8. Keep it growing

Add more sources anytime. Klore compiles incrementally — only new or changed sources are reprocessed:

```bash
klore add another-paper.pdf
klore compile          # only processes the new file
klore lint             # check for contradictions, broken links
klore diff --since 1w  # see what changed in the wiki this week
```

## How it works

Klore runs a three-pass compiler:

1. **Pass 1 — Source Extraction** (fast model, concurrent): Each raw source is converted to markdown and summarized by an LLM. Output: `wiki/sources/*.md` with titles, summaries, key claims, concept tags, and provenance links back to the raw file.

2. **Tag Normalization**: Synonym tags are merged into canonical forms ("ML" → "machine-learning"). Prevents concept fragmentation.

3. **Pass 2 — Concept Synthesis** (strong model, concurrent): For each concept that appears in 2+ sources, the LLM synthesizes a concept article that cross-references all contributing sources. Output: `wiki/concepts/*.md`.

4. **Pass 3 — Index Generation** (strong model): Master index, concept index, source index, and a link graph are generated. Output: `wiki/INDEX.md`, `wiki/_meta/link-graph.json`.

The wiki is Obsidian-compatible out of the box — `[[wikilinks]]`, backlinks, and graph view all work.

## Commands

```
klore init [name]            # Create a new knowledge base
klore add <file|url>         # Add a source (PDF, HTML, markdown, image, URL)
klore compile                # Compile sources into the wiki (incremental)
klore compile --full         # Force full recompilation
klore ask "question"         # Ask a question against the wiki
klore ask --save "question"  # Ask and save the answer as a wiki report
klore lint                   # Run health checks (contradictions, broken links)
klore diff [--since 2w]      # Show wiki changes over time
klore status                 # Show source/concept counts, compilation state
klore config set <key> <val> # Configure models, API key
```

## Model Configuration

Klore uses [OpenRouter](https://openrouter.ai) for model-agnostic LLM access. One API key, any model.

| Tier | Default Model | Used for |
|------|--------------|----------|
| Fast | `google/gemini-2.5-flash` | Source extraction, tag normalization |
| Strong | `anthropic/claude-sonnet-4-6` | Concept synthesis, Q&A, linting |

Override models:
```bash
klore config set model.fast google/gemini-2.5-pro
klore config set model.strong openai/gpt-4o
```

## Architecture

```
my-research/
├── raw/                     # Your source files (never modified by Klore)
│   ├── paper1.pdf
│   ├── article.md
│   └── diagram.png
├── wiki/                    # Compiled output (Obsidian-compatible)
│   ├── AGENTS.md            # Wiki schema (editable)
│   ├── INDEX.md             # Master index
│   ├── concepts/            # Synthesized concept articles
│   ├── sources/             # Per-source summaries
│   ├── reports/             # Saved Q&A answers
│   └── _meta/               # Compilation state, link graph
├── .klore/config.json       # Configuration
└── .git/                    # Auto-initialized, wiki changes tracked
```

## Key design decisions

- **No vector database.** No embeddings. No RAG. The compiled wiki is loaded directly into the LLM's context window.
- **Obsidian-native.** The wiki is a folder of `.md` files with `[[wikilinks]]`. Open it in Obsidian for graph view, backlinks, and search.
- **Incremental compilation.** Only new or changed sources are reprocessed. Prompt changes trigger automatic full recompile.
- **Git-tracked.** Every compilation auto-commits the wiki. `klore diff` shows how your knowledge base evolved.
- **Model-agnostic.** Any OpenRouter model works. Swap models with one config change.

## Inspired by

[Andrej Karpathy's description](https://karpathy.ai) of his personal LLM-powered knowledge base workflow.

## License

MIT
