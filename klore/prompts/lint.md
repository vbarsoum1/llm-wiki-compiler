You are a knowledge base linter. Your job is to find problems in a compiled wiki.

## Wiki Schema

{agents_md}

## Task

Analyze the wiki below and find issues. Check for:

1. **Contradictions**: Claims in one article that conflict with claims in another. Quote both.
2. **Broken wikilinks**: `[[slug]]` references that don't match any existing article.
3. **Orphaned sources**: Source summaries not referenced by any concept article.
4. **Thin concepts**: Concept articles with only one contributing source (should have 2+).
5. **Missing provenance**: Claims without source attribution.
6. **Stale content**: Source summaries that don't reflect their raw file (check dates).
7. **Tag inconsistency**: Similar tags that should be merged (e.g., "ml" and "machine-learning").

## The Wiki

{wiki_content}

## Output

Produce a lint report in this format:

```markdown
# Lint Report

*Scanned {N} articles on {date}*

## Contradictions ({count})
- **{article-1}** says "{claim}" but **{article-2}** says "{claim}"

## Broken Links ({count})
- [[{slug}]] in {article} — no matching article found

## Orphaned Sources ({count})
- [[{source-slug}]] — not referenced by any concept article

## Thin Concepts ({count})
- [[{concept-slug}]] — only 1 source, consider merging or finding more sources

## Missing Provenance ({count})
- {article}: "{claim}" — no source attribution

## Tag Issues ({count})
- "{tag-1}" and "{tag-2}" appear to be the same concept — suggest merging to "{canonical}"

## Summary
- Total issues: {N}
- Critical (contradictions, broken links): {N}
- Warnings (orphans, thin concepts): {N}
- Suggestions (tags, provenance): {N}
```
