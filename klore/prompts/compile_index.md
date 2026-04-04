You are a knowledge compiler. Your job is to generate the master index file for a wiki.

This index is a navigational catalog — it helps readers and the LLM find relevant pages. It should be comprehensive but scannable.

## Wiki Schema

{agents_md}

## Task

Generate the master index for this wiki.

Requirements:
- Do NOT use [[wikilinks]] — use plain text names. The index is for reading and navigation, not for graph links.
- Group concepts by their primary theme
- List sources chronologically (newest first)
- List entities by type (people, organizations, technologies)
- Include accurate counts
- Include one-line descriptions for each entry

## Current Wiki Contents

### Concepts ({concept_count} total)
{concept_list}

### Entities ({entity_count} total)
{entity_list}

### Sources ({source_count} total)
{source_list}

### Reports ({report_count} total)
{report_list}

## Output

Produce ONLY the markdown content for the index file. No explanation, no wrapping. Start with `# ` heading.

Format:

# Knowledge Base Index

*{N} sources, {M} concepts, {E} entities. Last compiled: {date}*

## Concepts
### {Theme}
- concept-slug — one-line description

## Entities
### People
- entity-slug — one-line description
### Organizations
- entity-slug — one-line description
### Technologies
- entity-slug — one-line description

## Sources
- source-slug — title (date)

## Reports
- report-slug — question asked (date)
