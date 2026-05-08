---
description: View and act on the unsubscribe queue. List recommended/completed/failed; attempt one or all; ignore senders; manually mark resolved.
argument-hint: [list | attempt <id-or-pattern> | attempt-all | ignore <id-or-pattern> | retry <id-or-pattern> | mark-done <id> | brief]
---

You are managing the inbox unsubscribe queue (`efc.unsubscribe_queue`). Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`. For attempting actual unsubscribes, use the **claude-in-chrome MCP** for Tier 2 browser fallback per the `unsubscribe-manager` skill.

## Step 1 — Parse subcommand

| Subcommand | Behavior |
|---|---|
| (empty) or `list` | Show queue grouped by status |
| `attempt <id-or-pattern>` | Try Tier 1 then Tier 2 unsubscribe for one entry |
| `attempt-all` | Walk all `recommended` entries, attempt each (asks confirmation if >5) |
| `ignore <id-or-pattern>` | status='ignored', stop tracking |
| `retry <id-or-pattern>` | Reset failed entries to recommended for re-attempt |
| `mark-done <id>` | Manually mark completed (Dave handled it externally) |
| `brief` | Generate the Monday-8:30-AM-style brief on demand |

## list (default)

```sql
SELECT id, sender_email, sender_pattern, sample_subject, times_seen, status,
       unsubscribe_url, list_unsubscribe_post, attempted_at, completed_at, failure_reason
FROM efc.unsubscribe_queue
WHERE status IN ('recommended','attempting','failed')
ORDER BY status, times_seen DESC;
```

Output:

```
✂️ UNSUBSCRIBE QUEUE

⏳ Recommended (<N>) — auto-attempt eligible
  • <sender_email> [<times_seen>x]   id: <short>
        sample: "<subject snippet>"
        <one-click POST: yes / no>  <browser URL: yes / no>
  • ...

❌ Failed (<N>) — auto attempted, didn't work
  • <sender> [<times_seen>x]   id: <short>
        reason: <failure_reason>
        URL: <unsubscribe_url>  ← click to handle manually
  • ...

✅ Completed (this month, <N>) — done
  • <sender_pattern>  — completed <date>

🚫 Ignored (<N>) — Dave told us to stop tracking these

— Run /inbox-unsubscribe attempt <id> to try one. attempt-all for everything recommended.
```

## attempt <id-or-pattern>

Resolve id (prefix match) or pattern. Pull the row.

**Tier 1 (RFC 8058 one-click POST):**
If `list_unsubscribe_post` is set, execute via Bash:
```bash
curl -X POST "<list_unsubscribe_post>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "List-Unsubscribe=One-Click" \
  -m 15 -w "%{http_code}" -o /tmp/unsub-response
```

If response code is 2xx → SUCCESS, jump to "Mark complete" below.
If 4xx/5xx → log Tier 1 result and try Tier 2.

**Tier 2 (Chrome MCP):**
If `unsubscribe_url` is set:
- Use `mcp__Claude_in_Chrome__navigate` to load the URL (in a new tab)
- Take a screenshot
- Look for a one-click confirm button (text matching unsubscribe / confirm / yes, remove me)
- If found and clear → click via `mcp__Claude_in_Chrome__computer`
- If form requires email field → fill with the destination account email
- If CAPTCHA / login wall / form too complex → mark FAILED

Take a final screenshot to verify success state, save to memory.

**Mark complete:**
```sql
UPDATE efc.unsubscribe_queue
SET status='completed', completed_at=now(), attempted_at=now()
WHERE id='<full-uuid>';
```

**Auto-create archive rule:**
```sql
INSERT INTO efc.inbox_rules (name, rule_type, conditions, action, active, created_by, notes)
VALUES (
  'Auto-archive after unsub: <sender>',
  'auto_archive',
  jsonb_build_object('from', '<sender_pattern>', 'match_logic', 'and'),
  jsonb_build_object('apply', 'archive_in_gmail'),
  true, 'autonomous', 'Created on unsub success <date>'
);
```

Confirm in chat:
```
✓ Unsubscribed: <sender>  (Tier <1|2>)
   Auto-archive rule created — future emails from this sender vanish.
```

**On failure:**
```sql
UPDATE efc.unsubscribe_queue
SET status='failed', attempted_at=now(), failure_reason='<reason>'
WHERE id='<full-uuid>';
```

```
✗ Auto-unsubscribe failed for <sender>: <reason>
   Manual link: <unsubscribe_url>
```

## attempt-all

Pull all `recommended` entries.

If count > 5: ask "Attempt unsubscribe for <N> senders? (yes/no/limit-N)". Wait for response.

For each entry, do the attempt above. Track running tally. Throttle 2 sec between attempts to be polite.

Final summary:
```
Attempted N unsubscribes:
  ✓ Tier 1 success: <count>
  ✓ Tier 2 success: <count>
  ✗ Failed (manual needed): <count>
  Skipped: <count>
```

## ignore <id-or-pattern>

```sql
UPDATE efc.unsubscribe_queue SET status='ignored', updated_at=now()
WHERE id='<id>' OR sender_pattern='<pattern>';
```

## retry <id-or-pattern>

```sql
UPDATE efc.unsubscribe_queue SET status='recommended', failure_reason=NULL, updated_at=now()
WHERE id='<id>' AND status='failed';
```

Then suggest: "Run /inbox-unsubscribe attempt <id> to try again."

## mark-done <id>

For when Dave handled it via Gmail directly:
```sql
UPDATE efc.unsubscribe_queue
SET status='completed', completed_at=now(), notes='Manually handled by Dave'
WHERE id='<id>';
```

## brief

Same format as the `dave-os-weekly-unsubscribe-brief` routine. Generate on-demand.

## Rules

- Always confirm writes with one short line.
- Don't claim a Tier 2 success unless you actually saw the confirmation page render. Screenshot → verify → claim.
- For attempt-all with >20 entries, hard-stop and ask Dave to confirm.
- Throttle browser-driven attempts (2 sec between) to avoid looking abusive.
- Never delete a queue row — `ignored` is the closest to delete and it's reversible.
