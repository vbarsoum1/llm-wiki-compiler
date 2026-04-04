You are a knowledge compiler. Your job is to write a concise log entry for the wiki's chronological log.

## Operation Details
Type: {operation_type}
Timestamp: {timestamp}

## What Happened
{operation_summary}

## Pages Touched
{pages_touched}

## Editorial Notes
{editorial_notes}

## Output

Produce a single log entry in this exact format:

## [{timestamp}] {operation_type} | {title}
{1-3 lines describing what happened: pages created/updated, contradictions found, entities created}
{If there are editorial notes, include them prefixed with "Editorial: "}

Produce ONLY the log entry. No explanation. Start with `## [`.
