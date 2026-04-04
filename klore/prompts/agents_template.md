# Wiki Schema & Conventions

This file defines the structure, formatting, and rules for the compiled wiki.
The LLM reads this file before every compilation pass. Edit it to customize
how your knowledge base is organized.

## Three-Tier Model Architecture

- **Director** (editorial judgment): Maintains `overview.md`, decides when to
  create/merge concept and entity pages, resolves contradictions.
- **Strong** (synthesis): Writes concept articles, entity pages, and reports.
  Synthesizes across multiple sources.
- **Fast** (extraction): Ingests raw sources into `wiki/sources/` summaries.
  Extracts claims, tags, and entity references.

## Directory Structure

```
wiki/
├── index.md          # Master catalog (plain text, no wikilinks)
├── log.md            # Append-only chronological record
├── overview.md       # Living synthesis (Director-maintained)
├── sources/          # Per-source summaries
├── concepts/         # Synthesized concept articles (Director-recommended)
├── entities/         # Named entity pages (people, orgs, tech)
├── reports/          # Filed Q&A answers (compound back into wiki)
└── _meta/            # Compilation state, link graph
```

## File Naming

- All filenames are **slugified**: lowercase, hyphens for spaces, no special characters.
- Source summaries: `wiki/sources/{slug}.md` (slug derived from source title)
- Concept articles: `wiki/concepts/{slug}.md` (slug derived from concept name)
- Entity pages: `wiki/entities/{slug}.md` (slug derived from entity name)
- Reports: `wiki/reports/{slug}.md` (slug derived from question or report title)
- Single index: `wiki/index.md` (lowercase). No subdirectory INDEX files.

## Source Summary Format

Every raw source gets a summary in `wiki/sources/`. Format:

```markdown
---
title: "{source title}"
source: "{path to raw file, relative to raw/}"
date: "{publication date if known, otherwise ingestion date}"
author: "{author if known}"
tags: ["{tag-1}", "{tag-2}", "{tag-3}"]
entities: ["{entity-slug-1}", "{entity-slug-2}"]
---

# {Source Title}

**Source:** [[raw/{relative path}]]

## Summary

{3-5 sentence summary of the source. Focus on what it contributes to the
knowledge base — key findings, methods, claims, data. Be specific.}

## Key Claims

- **{Claim 1}**: {One-sentence statement with specific evidence.}
  *Provenance: {quote or page/section reference from the raw source}*

- **{Claim 2}**: {One-sentence statement with specific evidence.}
  *Provenance: {quote or page/section reference from the raw source}*

{3-8 key claims per source. Each must be traceable to the raw material.}

## Related Concepts

- [[{concept-slug}]] — {one-line explanation of how this source relates}
- [[{concept-slug}]] — {one-line explanation}

## Metadata

- **Format:** {pdf, html, markdown, image, etc.}
- **Word count:** {approximate}
- **Added:** {ISO date when ingested}
```

## Entity Page Format

Entity pages live in `wiki/entities/`. They track named entities — people,
organizations, technologies, and products — across sources. Create an entity
page when the Director determines the entity has enough substance and
navigational value for a standalone page.

```markdown
---
title: "{Entity Name}"
type: entity
entity_type: "{person|organization|technology|product}"
sources: ["{source-slug-1}", "{source-slug-2}"]
tags: ["{tag-1}", "{tag-2}"]
---

# {Entity Name}

## Overview
2-3 sentence factual description.

## Key Facts
- Important factual details from sources.

## Across Sources
### From [[{source-slug}]]
What this source says about the entity.

## Related Entities
- [[{entity-slug}]] — {relationship}

## Related Concepts
- [[{concept-slug}]] — {how this entity relates}
```

## Concept Article Format

Concept articles live in `wiki/concepts/`. They synthesize knowledge about
significant ideas. Create a concept article when the Director determines the
concept is significant enough for a standalone page — based on depth of
treatment and explanatory weight, not frequency of mention.

```markdown
---
title: "{Concept Name}"
tags: ["{tag-1}", "{tag-2}"]
sources: ["{source-slug-1}", "{source-slug-2}"]
entities: ["{entity-slug}"]
---

# {Concept Name}

## Definition

{2-3 sentence clear definition. Write for someone encountering this concept
for the first time in this knowledge base.}

## Evidence

{Synthesize what the sources say about this concept. Reference specific sources
using wikilinks: [[source-slug]]. Note where sources agree and where they differ.
If sources contradict each other, state both positions clearly.}

## Related Concepts

- [[{concept-slug}]] — {relationship description}
- [[{concept-slug}]] — {relationship description}

## Related Entities

- [[{entity-slug}]] — {how this entity relates to the concept}

## Sources

- [[{source-slug-1}]] — {what this source contributes to understanding this concept}
- [[{source-slug-2}]] — {what this source contributes}
```

## Index Format (`wiki/index.md`)

A single master index. No subdirectory INDEX files. Plain text only — no wikilinks.

```markdown
# Knowledge Base Index

*{N} sources, {M} concepts, {E} entities. Last compiled: {date}*

## Concepts
### {Theme}
- concept-slug — one-line description

## Entities
### People
- entity-slug — description
### Organizations
- entity-slug — description
### Technologies
- entity-slug — description

## Sources
- source-slug — title (date)

## Reports
- report-slug — question (date)
```

## Log Format (`wiki/log.md`)

Append-only chronological record. Every compilation action is logged here.

```markdown
## [{ISO timestamp}] {action} | {title}
{1-3 lines: pages created/updated, contradictions found, etc.}
```

Actions: `ingest`, `query`, `lint`, `schema`

## Overview Format (`wiki/overview.md`)

Living synthesis page maintained by the Director model. Updated after each
ingestion or when the knowledge base changes materially.

Structure:

- **Synthesis** — What does this knowledge base know, taken as a whole?
- **Key Themes** — Major themes that emerge across sources.
- **Agreements** — Where sources converge.
- **Contradictions** — Where sources conflict, with citations.
- **Open Questions** — What remains unanswered.
- **Suggested Next Sources** — What to read next to fill gaps.

## Cross-Linking Rules

- Use Obsidian-style wikilinks: `[[slug]]` or `[[slug|display text]]`
- Link concept-to-concept, concept-to-source, concept-to-entity, entity-to-entity
- Link source-to-concept and source-to-entity for every relevant tag
- Entity pages link to sources, concepts, and other entities
- Reports link to sources and concepts they reference
- The index file does NOT use wikilinks (plain text for navigation only)
- Prefer linking to existing articles over creating new ones
- When in doubt about whether to create a new concept article, don't.
  Prefer inline mentions in source summaries over thin standalone pages.

## Tag Rules

- Tags are lowercase, hyphenated: `machine-learning`, `transformer-architecture`
- Use the most specific tag that applies: `attention-mechanisms` over `deep-learning`
- Limit to 3-5 tags per source
- Reuse existing tags from the wiki before inventing new ones

## Entity Rules

- Create an entity page when a named entity has enough substance for a
  meaningful standalone page. Passing mentions belong inline in source summaries.
- Entity types: `person`, `organization`, `technology`, `product`
- Entity pages track facts and appearances across sources, NOT abstract ideas
  (those belong in concept articles).
- Entities link to both sources and concepts.

## Reports

Reports live in `wiki/reports/`. They are part of the knowledge graph, not
dead-end files. After a report is generated:

- It links to the sources and concepts it references.
- Relevant concept and entity pages are updated to reference the report.
- The report appears in `wiki/index.md` under the Reports section.

## Writing Style

- Be specific, not generic. "Achieves 95% accuracy on MMLU" over "performs well"
- Attribute claims to sources. "According to [[source-slug]], ..."
- When sources conflict, present both sides without taking a position
- Write for a technical audience. Don't over-explain basics.
- Keep summaries concise. The raw source is the authority — the wiki is the map.
- Entity pages should be factual, not analytical.
- The overview page should be opinionated and synthesizing.
- Log entries should be concise and parseable with grep.
