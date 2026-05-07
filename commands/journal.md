---
description: Capture an observation, mood, body/energy note, or anything that's a state — not an action item. Goes to efc.journal_entries (not the inbox).
argument-hint: <observation, freeform>
---

You are writing an entry to Dave's journal in Supabase. **This is not a task.** Journal entries capture *state* — observations, mood, energy, body, food, medication, relationships, thoughts. Action items go through `/capture`.

**Process:**
1. Take whatever the user wrote (the argument). If empty, prompt once: *"What do you want to note?"* and wait.
2. Insert one row into `efc.journal_entries` via the **supabase MCP** (`mcp__*__execute_sql`, project_id `psmkklhyfkivyokhaiga`).
3. Confirm in **one line.** Show the journal-entry id and a short echo. No coaching.

**SQL pattern:**

```sql
INSERT INTO efc.journal_entries (entry_text, source)
VALUES ($J$<the user's text>$J$, 'manual')
RETURNING id, entry_date, captured_at;
```

Use a unique dollar-quote tag (`$J$`, `$J1$`, etc.) that cannot collide with the text.

**Output shape:**

```
✓ Journaled. (efc.journal_entries id: <id>)
   "<echo of the text, max 80 chars>"
```

**Rules:**
- Keep the response under 3 lines. Capture is fast or it isn't capture.
- Do not classify mood, energy, or topics at write time. The nightly reflection job will tag entries asynchronously. Speed matters more than structure here.
- Do not coach, don't comment on what was journaled, don't ask follow-up questions. Just write and confirm.
- If the entry obviously contains medical / health / medication content, **still write it.** Dave authorized this in his operating manual. Do not gatekeep his own data.
- One write, one confirm, done.
- If the user accidentally journaled an action item ("call Karen tomorrow"), don't redirect — write it, then add one line: *"This reads action-shaped. Want me to also `/capture` it?"* That's the only deviation from the rule.
