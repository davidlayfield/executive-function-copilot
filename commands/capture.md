---
description: Drop something into your EFC inbox in seconds. The fastest way to get a thought out of your head.
argument-hint: <whatever's in your head — short or long>
---

You are capturing an item into Dave's EFC inbox in Supabase. **Do not coach. Do not plan. Just capture and confirm.** This is GTD-style frictionless capture.

**Process:**
1. Take whatever the user wrote (the argument). If empty, prompt once: *"What do you want to capture?"* and wait.
2. Insert into `efc.inbox_items` via the **supabase MCP** (`mcp__*__execute_sql`, project_id `psmkklhyfkivyokhaiga`).
3. Confirm in **one line.** Show the inbox-item id and a sentence echoing what was captured. No coaching. No prompts to triage now.

**SQL pattern:**

```sql
INSERT INTO efc.inbox_items (raw_text, source)
VALUES ($CAPTURE$<the user's text>$CAPTURE$, 'manual')
RETURNING id, captured_at;
```

Use a unique dollar-quote tag (`$CAPTURE$`, `$CAP1$`, etc.) that cannot collide with the text.

**Output shape:**

```
✓ Captured. (efc.inbox_items id: <id>)
   "<echo of the captured text, max 80 chars>"
```

**Rules:**
- Keep the response under 3 lines. Capture is fast or it isn't capture.
- Do not classify, prioritize, or assign to a project. That happens at /triage.
- Do not search OpenBrain or do anything else. One write, one confirm, done.
- If the user has dumped many items in one capture, **still create one inbox_item** with the full raw text. Splitting happens at triage. The inbox is allowed to be messy.
