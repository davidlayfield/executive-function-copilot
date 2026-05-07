---
description: Show pending EFC inbox items — what's been captured but not yet triaged.
argument-hint: [optional limit, default 25]
---

Show Dave the current state of his EFC inbox. Read-only. No triage.

**Process:**
1. Query `efc.inbox_items` via the supabase MCP (`mcp__*__execute_sql`, project_id `psmkklhyfkivyokhaiga`):

```sql
SELECT id, source, raw_text, extracted_action_item, captured_at,
       openbrain_memory_id IS NOT NULL AS from_openbrain
FROM efc.inbox_items
WHERE status = 'pending'
ORDER BY captured_at DESC
LIMIT 25;  -- or argument
```

2. Get the count of pending items separately:
```sql
SELECT count(*) FROM efc.inbox_items WHERE status='pending';
```

**Output shape:**

```
INBOX — <count> pending

Recent captures (newest first):

1. [<source>] <captured_at relative, e.g. "12 min ago">
   <raw_text or extracted_action_item, truncated at 120 chars>

2. ...

(showing N of M; run /triage to process)
```

**Rules:**
- One screen, no walls of text.
- If count > 20, say so explicitly and surface as a nudge: *"Inbox is over 20. Worth a /triage pass when you have a moment."* — once, not repeated.
- If from_openbrain is true, label the source as `openbrain` and append `(auto-extracted)` to that line.
- If `extracted_action_item` is non-null, show that instead of `raw_text` — it's the cleaned version.
- Do not coach. Do not propose triage decisions. Just show.
