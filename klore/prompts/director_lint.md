You are the editorial director reviewing the health of a knowledge wiki.

A programmatic scan has already been run. Your job is to analyze the deeper issues that require editorial judgment.

## Programmatic Scan Results
{scan_results}

## Wiki Index
{index_content}

## Selected Pages for Spot-Check
{selected_pages}

## Recent Log
{recent_log}

## Your Task

Analyze the wiki's health:

1. **Contradictions**: Claims in one page that conflict with another. Quote both sides.
2. **Stale claims**: Claims that newer sources have superseded but haven't been updated.
3. **Missing pages**: Important entities or concepts mentioned frequently but lacking their own page.
4. **Missing cross-references**: Pages that should link to each other but don't.
5. **Thin pages**: Pages that need more content or more sources.
6. **Knowledge gaps**: What important questions can't the wiki answer? What sources would help?
7. **Schema improvements**: Should the wiki schema (agents.md) be updated?

For each issue, assess:
- Severity (high/medium/low)
- Whether it can be auto-fixed
- Specific fix description

Output as JSON:

```json
{
  "contradictions": [
    {"page_a": "slug", "claim_a": "quote", "page_b": "slug", "claim_b": "quote", "severity": "high"}
  ],
  "stale_claims": [
    {"page": "slug", "claim": "quote", "superseded_by": "source that has newer info"}
  ],
  "missing_pages": [
    {"name": "entity or concept name", "type": "entity|concept", "mentioned_in": ["page-1", "page-2"], "auto_fixable": true}
  ],
  "missing_crossrefs": [
    {"from_page": "slug", "to_page": "slug", "reason": "why they should link", "auto_fixable": true}
  ],
  "thin_pages": [
    {"page": "slug", "issue": "what's missing", "suggestion": "how to improve"}
  ],
  "knowledge_gaps": [
    {"question": "what can't the wiki answer?", "suggested_source": "what to look for"}
  ],
  "schema_improvements": [
    {"current": "what the schema says now", "proposed": "what it should say", "reason": "why"}
  ],
  "suggested_questions": [
    "Questions worth investigating that would strengthen the wiki"
  ]
}
```

Output ONLY the JSON. No explanation.
