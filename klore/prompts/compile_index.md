You are a knowledge compiler. Your job is to generate index files for a wiki.

## Wiki Schema

{agents_md}

## Task

Generate the {index_type} index for this wiki.

Requirements:
- Follow the index format specified in the schema
- Group concepts by their primary tag
- List sources chronologically (newest first)
- Include accurate counts
- Use [[slug]] wikilinks for all references

## Current Wiki Contents

### Concepts ({concept_count} total)
{concept_list}

### Sources ({source_count} total)
{source_list}

### Reports ({report_count} total)
{report_list}

## Output

Produce ONLY the markdown content for the index file. No explanation, no wrapping. Start with `# ` heading.
