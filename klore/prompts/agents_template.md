# Wiki Schema & Conventions

This file defines the structure, formatting, and rules for the compiled wiki.
The LLM reads this file before every compilation pass. Edit it to customize
how your knowledge base is organized.

## File Naming

- All filenames are **slugified**: lowercase, hyphens for spaces, no special characters.
- Source summaries: `wiki/sources/{slug}.md` (slug derived from source title)
- Concept articles: `wiki/concepts/{slug}.md` (slug derived from concept name)
- Reports: `wiki/reports/{slug}.md` (slug derived from question or report title)

## Source Summary Format

Every raw source gets a summary in `wiki/sources/`. Format:

```markdown
---
title: "{source title}"
source: "{path to raw file, relative to raw/}"
date: "{publication date if known, otherwise ingestion date}"
author: "{author if known}"
tags: ["{tag-1}", "{tag-2}", "{tag-3}"]
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

## Concept Article Format

Concept articles live in `wiki/concepts/`. They synthesize across multiple sources.
Only create a concept article when 2+ sources reference the same concept.

```markdown
---
title: "{Concept Name}"
tags: ["{tag-1}", "{tag-2}"]
sources: ["{source-slug-1}", "{source-slug-2}"]
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

## Sources

- [[{source-slug-1}]] — {what this source contributes to understanding this concept}
- [[{source-slug-2}]] — {what this source contributes}
```

## Index Format

### Master Index (`wiki/INDEX.md`)

```markdown
# Knowledge Base Index

*{N} sources, {M} concepts. Last compiled: {ISO datetime}*

## Concepts

{Group concepts by their primary tag. List each with a one-line description.}

### {Tag Category}
- [[{concept-slug}]] — {one-line description}

## Sources

{Chronological list, newest first.}

- [[{source-slug}]] — {title} ({date})

## Reports

- [[{report-slug}]] — {question asked} ({date})
```

### Concept Index (`wiki/concepts/INDEX.md`)

List all concept articles with cross-links.

### Source Index (`wiki/sources/INDEX.md`)

Chronological list of all source summaries.

## Cross-Linking Rules

- Use Obsidian-style wikilinks: `[[slug]]` or `[[slug|display text]]`
- Link concept-to-concept when concepts are related
- Link source-to-concept for every concept tag
- Link concept-to-source for every contributing source
- Prefer linking to existing articles over creating new ones
- When in doubt about whether to create a new concept article, don't.
  Only create when 2+ sources discuss the same idea.

## Tag Rules

- Tags are lowercase, hyphenated: `machine-learning`, `transformer-architecture`
- Use the most specific tag that applies: `attention-mechanisms` over `deep-learning`
- Limit to 3-5 tags per source
- Reuse existing tags from the wiki before inventing new ones

## Writing Style

- Be specific, not generic. "Achieves 95% accuracy on MMLU" over "performs well"
- Attribute claims to sources. "According to [[source-slug]], ..."
- When sources conflict, present both sides without taking a position
- Write for a technical audience. Don't over-explain basics.
- Keep summaries concise. The raw source is the authority — the wiki is the map.
