<p align="center">
  <img src="klore-readme-banner.png" alt="Klore — LLM Knowledge Compiler" width="100%">
</p>

# Klore — LLM Wiki Knowledge Compiler

> An implementation of [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), with autonomous editorial judgment.

**Raw sources in, living knowledge base out.** Available as a standalone CLI or a **Claude Code plugin**.

Drop PDFs, articles, and images into a folder. Klore compiles them into a structured, interlinked Obsidian-compatible wiki — then answers your questions using the compiled knowledge, not retrieved fragments.

**The thesis:** RAG retrieves fragments. Klore compiles knowledge. With 1M+ token context windows, the compiled wiki IS the index.

Based on [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), extended with a three-tier model architecture where a Director model (Opus) replaces the human editorial role — reading each source deeply, deciding what matters, identifying contradictions, and maintaining a living synthesis.

## Getting Started

### Option A: Claude Code Plugin (recommended)

```bash
git clone https://github.com/vbarsoum1/llm-wiki-compiler.git
pip install ./llm-wiki-compiler
claude plugin install ./llm-wiki-compiler/klore/plugin
```

Then in Claude Code:
```
/wiki-init                    # Initialize a knowledge base
/wiki-ingest paper.pdf        # Add a source and compile
/wiki-ask "What are the key findings?"
```

The plugin auto-injects your wiki's index into every Claude Code session. Your knowledge base becomes ambient context.

### Option B: Standalone CLI

```bash
git clone https://github.com/vbarsoum1/llm-wiki-compiler.git
cd llm-wiki-compiler
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

Klore runs a director-driven compilation pipeline with three model tiers:

| Tier | Default Model | Role |
|------|--------------|------|
| **Director** | `anthropic/claude-opus-4.6` | Editorial judgment — reads sources, decides what matters, reviews quality, maintains the living synthesis |
| **Strong** | `google/gemini-3.1-pro-preview` | Concept synthesis, entity pages, Q&A answers |
| **Fast** | `google/gemini-3-flash-preview` | Source extraction, tag normalization |

### The compilation pipeline

1. **Extract** (fast, concurrent): Each raw source is converted to markdown.

2. **Editorial Brief** (director): The Director reads each source against the current wiki state and produces an editorial brief — what's important, what contradicts existing knowledge, what entities and concepts to create or update.

3. **Tag Normalization** (fast): Synonym tags merged into canonical forms.

4. **Build** (strong, concurrent): Source summaries, concept articles, and entity pages are written, guided by the Director's editorial briefs.

5. **Review** (director): The Director reviews the changes for quality and accuracy.

6. **Index & Log**: A single master index is generated. Every operation is appended to `wiki/log.md`.

7. **Overview** (director): The Director updates `wiki/overview.md` — a living synthesis of the entire knowledge base.

The wiki is Obsidian-compatible out of the box — `[[wikilinks]]`, backlinks, and graph view all work.

## Commands

```
klore init [name]            # Create a new knowledge base
klore add <file|url>         # Add a source (PDF, HTML, markdown, image, URL)
klore ingest <file|url>      # Add a source and compile in one step
klore compile                # Compile sources into the wiki (incremental)
klore compile --full         # Force full recompilation
klore compile --topic <name> # Recompile a specific concept only
klore ask "question"         # Ask a question against the wiki
klore ask --save "question"  # Ask and save the answer as a wiki report
klore watch                  # Watch raw/ for changes and auto-compile
klore lint                   # Run health checks (contradictions, broken links)
klore diff [--since 2w]      # Show wiki changes over time
klore status                 # Show source/concept counts, compilation state
klore config set <key> <val> # Configure models, API key
```

### Install as Claude Code Plugin

```bash
# Clone the repo
git clone https://github.com/vbarsoum1/llm-wiki-compiler.git

# Install the CLI
pipx install ./llm-wiki-compiler   # or: pip install ./llm-wiki-compiler

# Install the Claude Code plugin
claude plugin install ./llm-wiki-compiler/klore/plugin
```

Then in Claude Code: `/wiki-init`, `/wiki-compile`, `/wiki-ingest`, `/wiki-ask`, `/wiki-status`, `/wiki-lint`, `/wiki-watch`.

The plugin auto-injects your wiki's index into every Claude Code session via a SessionStart hook.

## Model Configuration

Klore uses [OpenRouter](https://openrouter.ai) for model-agnostic LLM access. One API key, any model.

| Tier | Default Model | Used for |
|------|--------------|----------|
| Director | `anthropic/claude-opus-4.6` | Editorial judgment, quality review, overview synthesis |
| Strong | `google/gemini-3.1-pro-preview` | Concept synthesis, entity pages, Q&A, linting |
| Fast | `google/gemini-3-flash-preview` | Source extraction, tag normalization |

Override models:
```bash
klore config set model.director anthropic/claude-sonnet-4-6
klore config set model.strong openai/gpt-4o
klore config set model.fast google/gemini-2.5-flash
```

## Architecture

```
my-research/
├── raw/                     # Your source files (never modified by Klore)
│   ├── paper1.pdf
│   ├── article.md
│   └── diagram.png
├── wiki/                    # Compiled output (Obsidian-compatible)
│   ├── index.md             # Master catalog (no wikilinks — navigation only)
│   ├── log.md               # Append-only chronological record of all operations
│   ├── overview.md          # Living synthesis — Director-maintained thesis
│   ├── sources/             # Per-source summaries
│   ├── concepts/            # Synthesized concept articles
│   ├── entities/            # Named entity pages (people, orgs, tech)
│   ├── reports/             # Filed Q&A answers (feed back into wiki)
│   └── _meta/               # Compilation state, link graph, lint reports
├── .klore/
│   ├── config.json          # Model and API configuration
│   └── agents.md            # Wiki schema — controls how sources are compiled (editable)
└── .git/                    # Auto-initialized, wiki changes tracked
```

## Key design decisions

- **Director-driven.** A frontier model (Opus) plays the editorial role — deciding what matters, what contradicts, and what to investigate next. This replaces the human-in-the-loop from Karpathy's original pattern.
- **No vector database.** No embeddings. No RAG. The compiled wiki is loaded directly into the LLM's context window.
- **Index-first queries.** Q&A reads the index to find relevant pages, then drills in — instead of loading everything. Scales to hundreds of sources.
- **Entity pages.** Named entities (people, orgs, technologies) get their own pages alongside concept articles, creating a rich relational graph.
- **Living synthesis.** `wiki/overview.md` is a continuously updated thesis about what the knowledge base means, taken as a whole.
- **Chronological log.** Every operation is logged in `wiki/log.md` — parseable with `grep "^## \[" log.md`.
- **Reports compound.** Q&A answers filed back into the wiki update concept and entity pages — knowledge compounds.
- **Obsidian-native.** The wiki is a folder of `.md` files with `[[wikilinks]]`. Open it in Obsidian for graph view, backlinks, and search.
- **Incremental compilation.** Only new or changed sources are reprocessed. Prompt changes trigger automatic full recompile.
- **Git-tracked.** Every compilation auto-commits the wiki. `klore diff` shows how your knowledge base evolved.
- **Model-agnostic.** Any OpenRouter model works. Swap models with one config change.

## Inspired by

[Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — extended with autonomous editorial judgment via a three-tier model architecture.

## License

MIT
