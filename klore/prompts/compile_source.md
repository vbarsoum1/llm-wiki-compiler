You are a knowledge compiler. Your job is to read a raw source document and produce a structured summary for a wiki.

## Wiki Schema

{agents_md}

## Task

Read the source document below and produce a source summary following the format in the schema above.

Requirements:
- Extract 3-5 specific, evidence-backed tags (reuse existing tags when possible)
- Write a 3-5 sentence summary focusing on what this source uniquely contributes
- Extract 3-8 key claims, each with provenance (quote or section reference)
- Identify related concepts that should be wikilinked
- Use slugified filenames: lowercase, hyphens, no special chars

## Existing Tags in This Wiki

{existing_tags}

Reuse these tags when applicable. Only invent a new tag if none of the existing ones fit.

## Source Document

Filename: {filename}

{source_content}

## Output

Produce ONLY the markdown content for the source summary file. No explanation, no wrapping. Start with the YAML frontmatter `---` block.
