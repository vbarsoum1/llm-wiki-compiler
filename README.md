<p align="center">
  <img src="klore-readme-banner.png" alt="Klore — LLM Knowledge Compiler" width="100%">
</p>

<h3 align="center">Compile your research into durable LLM context.</h3>

<p align="center">
  <a href="https://pypi.org/project/klore/"><img src="https://img.shields.io/pypi/v/klore?color=blue" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://github.com/vbarsoum1/llm-wiki-compiler/stargazers"><img src="https://img.shields.io/github/stars/vbarsoum1/llm-wiki-compiler?style=social" alt="Stars"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Claude_Code-supported-blue" alt="Claude Code">
  <img src="https://img.shields.io/badge/Cursor-supported-blue" alt="Cursor">
  <img src="https://img.shields.io/badge/Windsurf-supported-blue" alt="Windsurf">
  <img src="https://img.shields.io/badge/Codex-supported-blue" alt="Codex">
  <img src="https://img.shields.io/badge/Copilot-supported-blue" alt="Copilot">
</p>

---

**Klore turns raw source material into a persistent, agent-readable knowledge base.** LLMs forget. RAG retrieves fragments. Klore compiles your documents into structured markdown: source summaries, concept pages, entity profiles, cross-references, saved reports, and a living overview that gets richer over time.

The output is plain [Obsidian](https://obsidian.md/)-compatible markdown that you own. Your coding agent can read it. Your editor can browse it. Git can track it. No vector database required.

Based on [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), extended with a three-tier model architecture where a Director model replaces the human editorial role.

## Why Klore?

```
RAG:     query → search chunks → answer → forget
Klore:   sources → compile → wiki → query → save → richer wiki → better answers
```

RAG is useful when you need an answer from a pile of documents. Klore is for when the pile itself needs to become usable knowledge.

RAG retrieves chunks at query time. Every question rediscovers the same relationships from scratch. The answer usually disappears back into chat history.

Klore compiles sources ahead of time. Concepts get their own pages. Entities accumulate profiles. Reports saved with `klore ask --save` feed future synthesis. The knowledge base becomes a durable context layer for humans and agents.

**Before:** read 3,200+ lines of raw files per session.<br>
**After:** read the index plus 2 topic articles, around 330 lines.<br>
**Result:** roughly 90% less context for the same working knowledge.

## What You Get

Klore writes a local markdown knowledge base:

```text
wiki/
├── index.md              # master map of the knowledge base
├── overview.md           # continuously updated synthesis
├── log.md                # chronological operation history
├── sources/              # per-source summaries with provenance
├── concepts/             # synthesized articles across sources
├── entities/             # people, organizations, products, technologies
├── reports/              # saved Q&A answers that feed future synthesis
└── _meta/                # compile state, link graph, tag aliases
```

That gives you:

- **Compiled context:** source material condensed into pages agents can load directly.
- **Persistent memory:** saved answers become part of the corpus instead of disappearing.
- **Editorial structure:** a Director model decides what deserves pages, what changed, and what should be linked.
- **Local ownership:** raw files and generated wiki stay on disk as plain files.
- **Git history:** every compile can be tracked and diffed.
- **Agent compatibility:** Claude Code, Cursor, Windsurf, Codex, Gemini, and Copilot can all use the same wiki context.

## Quick Start

### Install

```bash
pipx install klore    # or: pip install klore
```

### Set up your API key

Klore uses [OpenRouter](https://openrouter.ai) for model access. One key, any model:

```bash
export OPENROUTER_API_KEY="sk-or-v1-your-key-here"
```

### Build your first wiki

```bash
klore init my-research
cd my-research
klore add ~/papers/attention-is-all-you-need.pdf
klore add https://en.wikipedia.org/wiki/Transformer_(deep_learning_model)
klore compile
```

Open `wiki/` in [Obsidian](https://obsidian.md/) and explore. Or just read the markdown.

## Agent Memory

Klore gives coding agents persistent project memory made from your sources, not just chat history. Run `bash setup.sh` to auto-configure all detected agents, or set up manually:

| Agent | Setup | How it works |
|-------|-------|-------------|
| **[Claude Code](https://claude.ai/code)** | `claude plugin marketplace add ./klore/plugin && claude plugin install klore` | `/wiki-init`, `/wiki-compile`, `/wiki-ask`, `/wiki-longform` slash commands + SessionStart hook |
| **[Cursor](https://cursor.com)** | Open project in Cursor | Auto-loads `.cursor/rules/klore.mdc` |
| **[Windsurf](https://windsurf.com)** | Open project in Windsurf | Auto-loads `.windsurf/rules/klore.md` via Cascade |
| **[Codex (OpenAI)](https://openai.com/codex)** | Open project with Codex | Auto-loads `AGENTS.md` |
| **[Gemini (Google)](https://aistudio.google.com)** | Open project with Gemini | Auto-loads `GEMINI.md` |
| **[GitHub Copilot](https://github.com/features/copilot)** | Works automatically | Reads `.github/copilot-instructions.md` |

After setup, your agent can run klore commands directly. In Claude Code, use `/wiki-*` slash commands, including `/wiki-longform` for publication-ready articles grounded in the compiled wiki. In other agents, ask: "compile the wiki" or "ingest this article".

The Claude Code plugin also injects your wiki's index into every session via a SessionStart hook, so your knowledge base becomes ambient context.

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
klore longform "topic"       # Generate a grounded long-form article
klore watch                  # Watch raw/ for changes and auto-compile
klore lint                   # Run health checks (contradictions, broken links)
klore diff [--since 2w]      # Show wiki changes over time
klore status                 # Show source/concept counts, compilation state
klore config set <key> <val> # Configure models, API key
```

## How It Works

Klore runs a 7-step director-driven compilation pipeline with three model tiers:

| Tier | Default Model | Role |
|------|--------------|------|
| **Director** | Gemini 3.0 Flash Preview | Editorial judgment, quality review, synthesis |
| **Strong** | Gemini 3.0 Flash Preview | Concept pages, entity pages, Q&A |
| **Fast** | Gemini 3.0 Flash Preview | Source extraction, tag normalization |

### The Pipeline

1. **Extract** (fast, concurrent) — convert raw sources to markdown
2. **Editorial Brief** (director) — read each source against wiki state, decide what matters, flag contradictions
3. **Tag Normalize** (fast) — merge synonym tags into canonical forms
4. **Build** (strong, concurrent) — write source summaries, concept articles, entity pages, guided by editorial briefs
5. **Review** (director) — review changes for quality and accuracy
6. **Index & Log** — generate master index with `[[wikilinks]]`, append to operation log
7. **Overview** (director) — update `wiki/overview.md`, the living synthesis of the entire knowledge base

The Director model makes the editorial decisions that matter: what's significant, what contradicts existing knowledge, what deserves its own page, and what doesn't. This replaces the human-in-the-loop from Karpathy's original pattern.

## Cost

The three-tier architecture keeps costs low. The Director handles editorial judgment. The bulk of work runs on cheaper models.

| Sources | Est. Cost | Per Source |
|---------|-----------|-----------|
| 5 | ~$0.30 | ~$0.06 |
| 10 | ~$0.60 | ~$0.06 |
| 25 | ~$1.50 | ~$0.06 |
| 50 | ~$3.00 | ~$0.06 |

Real-world example: compiled a 57,000-word book (11 chapters) into 20 concept pages, 2 entity pages, and a full synthesis for ~$0.50 using Gemini Flash 3.0.

Incremental compiles are cheaper. Adding one source to an existing wiki costs ~$0.05-0.10.

Override models anytime:
```bash
klore config set model.director google/gemini-3-flash-preview
klore config set model.strong google/gemini-3-flash-preview
klore config set model.fast google/gemini-3-flash-preview
```

## Architecture

```
my-research/
├── raw/                     # Your source files (never modified by Klore)
│   ├── paper1.pdf
│   ├── article.md
│   └── diagram.png
├── wiki/                    # Compiled output (Obsidian-compatible)
│   ├── index.md             # Master catalog with [[wikilinks]]
│   ├── log.md               # Append-only operation log
│   ├── overview.md          # Living synthesis (Director-maintained)
│   ├── sources/             # Per-source summaries
│   ├── concepts/            # Synthesized concept articles
│   ├── entities/            # Named entity pages (people, orgs, tech)
│   └── reports/             # Filed Q&A answers (feed back into wiki)
├── .klore/
│   ├── config.json          # Model and API configuration
│   └── agents.md            # Wiki schema (editable)
└── .git/                    # Auto-initialized, wiki changes tracked
```

## Design Decisions

- **Director-driven.** A frontier model plays editor, deciding what matters and what contradicts. No human-in-the-loop required.
- **No vector database.** No embeddings. No RAG. The compiled wiki loads directly into the LLM context window.
- **Entity pages.** People, organizations, and technologies get their own pages, creating a rich relational graph.
- **Living synthesis.** `wiki/overview.md` is continuously updated as sources are added.
- **Reports compound.** Q&A answers filed with `klore ask --save` are tagged with related concept pages and included in future concept synthesis. Knowledge compounds.
- **Obsidian-native.** Plain `.md` files with `[[wikilinks]]`. Graph view, backlinks, and search all work.
- **Incremental.** Only new or changed sources are reprocessed. Prompt changes trigger full recompile.
- **Git-tracked.** Every compilation auto-commits. `klore diff` shows how knowledge evolved.
- **Model-agnostic.** Any OpenRouter model. Swap with one config change.

## Inspired By

[Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — extended with autonomous editorial judgment via a three-tier model architecture.

## License

MIT
