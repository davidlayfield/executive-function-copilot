---
description: Archive the source Gmail thread for a task without marking the task done. Use when you handled the email outside Dave OS but want to clear it from the inbox.
argument-hint: <task id> [--read]
---

Archive the source Gmail thread for one inbox-AI task. Does NOT change the task's status — use `/inbox-update <id> done` if you want both.

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Resolve id and pull source info

```sql
SELECT id, title, source_account, source_email_id, thread_id, status
FROM efc.tasks
WHERE id::text LIKE '<prefix>%'
LIMIT 2;
```

If 0 → "No task with id <prefix>." Stop.
If 2+ → ask for more chars.
If 1 → continue.

If `source_account IS NULL OR thread_id IS NULL` → "Task has no source Gmail thread (manually captured task). Nothing to archive."

## Step 2 — Archive on Ralph

```bash
ssh -i ~/.ssh/LightsailDefaultKey-us-east-1.pem ubuntu@100.73.64.27 \
  "python3 /home/ubuntu/openbrain/connectors/gmail/gmail_archive.py \
   '<source_account>' '<thread_id>' --read"
```

`--read` is included by default (mark as read in addition to archive). Pass `--no-read` to keep unread (rare).

The helper returns JSON. Parse it:
- `{"ok": true, "kind": "thread", "id": "...", "messages": N}` → success
- `{"ok": false, "code": 403, "error": "...insufficientPermissions..."}` → token lacks `gmail.modify` scope (urbanorigin / dflayfield until re-auth)
- `{"ok": false, "code": 401, "error": "..."}` → token expired/invalid; the ingester should refresh on next call

## Step 3 — Log the action

Append a note to the task's notes field so the audit trail is preserved:

```sql
UPDATE efc.tasks
SET notes = COALESCE(notes, '') ||
            E'\n\n[ARCHIVED ' || to_char(now(), 'YYYY-MM-DD HH24:MI') ||
            '] Source Gmail thread archived (status unchanged).',
    updated_at = now()
WHERE id = '<full-uuid>'
RETURNING title;
```

## Step 4 — Confirm

Single line:

```
✓ Archived: "<task title>"
   Gmail: <N> messages archived in thread (account: <source_account>)
   Task status unchanged: <current status>
```

Or on scope error:

```
✗ Cannot archive: <source_account> token lacks gmail.modify scope.
   Re-auth that account with broader scope to enable. (See OAuth setup playbook.)
```

## Rules

- Never delete a Gmail thread. Archive only (removes INBOX label; thread stays in All Mail and can be unarchived from Gmail).
- Don't change task status — that's what `/inbox-update` is for.
- One archive per call; no batches in this command.
- For tasks with no source email (manual captures), refuse politely.
- For tasks where the archive would clear an email Dave hasn't seen yet (received in last 5 min), warn before archiving.
