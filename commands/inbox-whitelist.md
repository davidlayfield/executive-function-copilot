---
description: Manage Dave's newsletter whitelist (efc.newsletter_sources). list / add / remove / suggest. Whitelisted senders get story extraction + digest treatment instead of NOISE classification.
argument-hint: [list | add <pattern> | remove <id-or-pattern> | suggest | rename <id> <new name>]
---

You are managing Dave's newsletter whitelist in `efc.newsletter_sources`. Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Parse subcommand

| Subcommand | Behavior |
|---|---|
| (empty) or `list` | Show whitelisted + unreviewed sources |
| `add <pattern>` | INSERT new whitelisted entry (or move existing 'unreviewed' → 'whitelisted') |
| `remove <id\|pattern>` | DELETE or set status='blacklisted' (ask which) |
| `suggest` | Show top unreviewed sources sorted by frequency, prompt yes/no/skip per |
| `rename <id> <new name>` | UPDATE display_name |

If subcommand isn't recognized → show usage and stop.

## list (default)

```sql
SELECT id, display_name, sender_pattern, status, total_processed, last_processed_at
FROM efc.newsletter_sources
WHERE status IN ('whitelisted', 'unreviewed')
ORDER BY status, total_processed DESC NULLS LAST, display_name;
```

Output:

```
📰 NEWSLETTER WHITELIST

✅ Whitelisted (<count>)
  • <display_name> — <sender_pattern>
        <total_processed> emails processed; last <relative date>
        id: <short uuid>
  • ...

🤔 Unreviewed (<count>) — these look newslettery but aren't on the whitelist yet
  • <display_name or "(unknown)"> — <sender_pattern>
        seen <total_processed>x in last <how recent>
        id: <short uuid>

💡 Run /inbox-whitelist add <pattern> to whitelist, or remove <id> to drop.
   Run /inbox-whitelist suggest to walk through unreviewed entries one at a time.
```

If no whitelisted entries → "Whitelist is empty. Run /inbox-whitelist add <pattern> to start."

## add <pattern>

Pattern can be:
- A literal email: `newsletter@aisecret.us`
- A SQL `LIKE` pattern: `%@aisecret.us`, `newsletter%@%.com`
- A bare domain: `aisecret.us` (auto-converted to `%@aisecret.us`)

Process:
1. Normalize the pattern. Bare domain → `%@<domain>`. Bare email → exact match. Already SQL pattern → as-is.
2. Check if a row with this pattern exists:
   ```sql
   SELECT id, display_name, status FROM efc.newsletter_sources
   WHERE sender_pattern = '<normalized>';
   ```
3. If found and status='unreviewed' → UPDATE to 'whitelisted'. Confirm with display_name.
4. If found and status='whitelisted' → "Already whitelisted." Stop.
5. If found and status='blacklisted' or 'retired' → ask "Reactivate? (yes/no)"
6. If not found → INSERT. Generate display_name from pattern (e.g. `%@aisecret.us` → "AI Secret").

```sql
INSERT INTO efc.newsletter_sources (display_name, sender_pattern, status)
VALUES ('<inferred name>', '<pattern>', 'whitelisted')
RETURNING id, display_name;
```

Confirm:
```
✓ Whitelisted: <display_name> (<pattern>)
   Future emails matching this pattern will get story extraction.
```

## remove <id-or-pattern>

If arg starts with hex chars and is 7+ → treat as id prefix. Else treat as pattern.

Two action choices:
- **Soft remove** (set status='retired'): future emails go back to standard classification, but historical data stays
- **Hard delete**: only if user explicitly says "delete" 

Ask: "Retire (status only — historical kept) or delete (purge entirely)? Default retire."

```sql
-- Retire (default)
UPDATE efc.newsletter_sources SET status='retired'
WHERE id = '<id>' OR sender_pattern = '<pattern>'
RETURNING id, display_name, status;
```

Confirm.

## suggest

Walk through unreviewed entries one at a time, prompt Dave for each:

```sql
SELECT id, sender_pattern, total_processed, display_name
FROM efc.newsletter_sources
WHERE status = 'unreviewed'
ORDER BY total_processed DESC NULLS LAST
LIMIT 10;
```

For each (one at a time, wait for response):

```
[i/N] Unreviewed: <sender_pattern>
       Seen: <total_processed>x  | Display name guess: "<display_name>"
       Sample subjects:
         • "<subject 1>"
         • "<subject 2>"

       (a)dd to whitelist  /  (u)nsubscribe  /  (s)kip  /  (i)gnore forever  /  (q)uit
```

To get sample subjects, query the related emails:
```sql
SELECT subject FROM openbrain.email_bodies
WHERE from_address ILIKE replace(<sender_pattern>, '%', '%')
ORDER BY date_received DESC LIMIT 3;
```

Apply Dave's choice:
- **add** → status='whitelisted'
- **unsubscribe** → status='retired' on this row + INSERT into efc.unsubscribe_queue with status='recommended'
- **skip** → leave as-is, move to next
- **ignore** → status='blacklisted' (NEVER suggest again)
- **quit** → stop the walk

Show running tally at the end.

## rename <id> <new name>

```sql
UPDATE efc.newsletter_sources SET display_name = '<new>'
WHERE id = '<full-uuid-from-prefix>'
RETURNING id, display_name, sender_pattern;
```

## Rules

- Always show the pattern (`%@aisecret.us`) so Dave can see exactly what's being matched.
- Confirm writes in one line. No coaching.
- For `suggest`, only walk through items where total_processed >= 2 (one-off emails aren't worth reviewing).
- If the pattern would also match an existing whitelist entry (overlap), warn before adding.
- Never auto-blacklist anything. Dave makes the call.
