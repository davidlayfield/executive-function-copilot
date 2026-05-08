---
description: Update an inbox-AI task — mark done, push to a date, drop, mark waiting on someone, or reclassify. Logs the action so the contact-learning loop and rule-suggestion engine can use it.
argument-hint: <task id> <action> [arg]
---

You are updating an inbox-AI task based on Dave's decision. **Verify before writing** — if any part of the command is ambiguous, ask once and stop.

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Parse argument

Format: `<id> <action> [arg]`

Actions:
| Action | Arg | Effect |
|---|---|---|
| `done` | (none) | status='done', completed_at=now() |
| `doing` | (none) | status='doing' |
| `push <date>` | date string ("monday", "next-week", "2026-05-15", "+3d") | status='deferred', deferred_until=<date> |
| `drop` | (none) | status='dropped' |
| `waiting <person>` | person name or email | status='waiting', waiting_on_person=<name>, waiting_on_what=<inferred from task> |
| `reclassify <category>` | actionable\|ymyl\|informational\|noise\|spam\|newsletter | update efc.inbox_email_log.classification + log to learning |
| `priority <level>` | must\|should\|could | update efc.tasks.priority |
| `project <name>` | project name (existing or new) | attach to project; create if needed |

If action isn't in this list → "Action not recognized. Try: done / push / drop / waiting / reclassify / priority / project." Stop.

## Step 2 — Resolve id (prefix match if 7-char)

Same as `/inbox-show` step 1.

## Step 3 — Apply the change

After applying the status change, **if status='done' or 'dropped' AND the task has `source_account` + `thread_id` AND `source_account` is one of the OAuth-modify-scoped accounts** (gsh / housr.ai / apartmentsmart / urbanorigin once re-auth'd / dflayfield once re-auth'd), **archive the source Gmail thread** so it leaves Dave's inbox.

```bash
# Archive the source email thread on Ralph
ssh -i ~/.ssh/LightsailDefaultKey-us-east-1.pem ubuntu@100.73.64.27 \
  "python3 /home/ubuntu/openbrain/connectors/gmail/gmail_archive.py \
   '<source_account>' '<thread_id>' --read"
```

Result is JSON: `{"ok": true, "kind": "thread", "id": "<thread>", "messages": N}` on success, `{"ok": false, "code": 403, "error": "..."}` if scope missing.

Show one short line in the confirmation about the Gmail action:
- ✓ on success: `Gmail: archived <N> messages in thread`
- ⚠ on failure: `Gmail archive skipped (<reason>)` — never block the DB update on this; archive is a follow-on enrichment, not a hard dependency.

If `source_account` is `dflayfield@gmail.com` AND the gmail ingester used IMAP for that account (no OAuth), skip Gmail archive with: `Gmail: dflayfield uses IMAP — archive deferred (will land when OAuth scope is upgraded).`

For `dropped`: same archive call. Dave decided he doesn't want this email either way.

For `done`: same archive call. The task is closed; the source email's job is done.

For `waiting <person>`: do NOT archive. Dave still expects a reply.

For `push <date>`: do NOT archive. Dave is deferring, not closing.

```sql
-- Example: done
UPDATE efc.tasks
SET status = 'done', completed_at = now(), updated_at = now()
WHERE id = '<full-uuid>'
RETURNING id, title, status, sender_email, source_email_id, source_account, thread_id;

-- Example: push to a date
UPDATE efc.tasks
SET status = 'deferred', deferred_until = '<parsed-date>', updated_at = now()
WHERE id = '<full-uuid>' RETURNING id, title, status, deferred_until;

-- Example: drop
UPDATE efc.tasks
SET status = 'dropped', updated_at = now()
WHERE id = '<full-uuid>' RETURNING id, title, status;
```

## Step 4 — Contact learning loop

After a status change on an email-derived task, adjust the sender's importance_score in `efc.people` per the rules from `email-scoring` § "Special rules":

```sql
-- Per Clearpath PRD §10.6 contact-learning rules:
-- Dave acts within 4h: +0.05
-- Dave acts within 24h: +0.02
-- Dave acts > 72h: -0.02
-- Dave drops as noise/spam: -0.10
-- Floor 0.10, cap 1.00
WITH t AS (
  SELECT sender_email, status, created_at, completed_at
  FROM efc.tasks WHERE id = '<full-uuid>'
)
UPDATE efc.people
SET importance_score = LEAST(1.00, GREATEST(0.10, importance_score + (
  CASE
    WHEN (SELECT status FROM t) = 'done' AND
         EXTRACT(EPOCH FROM ((SELECT completed_at FROM t) - (SELECT created_at FROM t))) < 4*3600
      THEN 0.05
    WHEN (SELECT status FROM t) = 'done' AND
         EXTRACT(EPOCH FROM ((SELECT completed_at FROM t) - (SELECT created_at FROM t))) < 24*3600
      THEN 0.02
    WHEN (SELECT status FROM t) = 'done' AND
         EXTRACT(EPOCH FROM ((SELECT completed_at FROM t) - (SELECT created_at FROM t))) > 72*3600
      THEN -0.02
    WHEN (SELECT status FROM t) = 'dropped'
      THEN -0.10
    ELSE 0
  END
))
WHERE email_normalized = (SELECT lower(sender_email) FROM t);
```

## Step 5 — Reclassification special case

If action is `reclassify`, ALSO update `efc.inbox_email_log` and add a learning hint to `efc.inbox_sessions.notes` so the M2 routine can learn (3+ corrections from same sender → suggest a rule per `email-classification` § "Learning loop"):

```sql
UPDATE efc.inbox_email_log
SET classification = '<new>'
WHERE account = (SELECT source_account FROM efc.tasks WHERE id = '<id>')
  AND message_id = (SELECT source_email_id FROM efc.tasks WHERE id = '<id>');
```

## Step 6 — Confirm in one line

```
✓ <action_past_tense>: <title>
   <status detail>
   <importance_score change for sender, if any>
```

Examples:
- `✓ Done: Investigate Atlas daily sync TIMEOUT — sender importance +0.05`
- `✓ Pushed to 2026-05-12: Decide on CAHEC sponsorship`
- `✓ Dropped: Check AWS Personal Health Dashboard — sender importance -0.10`
- `✓ Reclassified noise → informational: <title>; learning recorded`

## Rules

- One write per call. No batches in this command.
- If task is already in target state (e.g., `/inbox-update <id> done` on a done task) → acknowledge and exit; don't re-write.
- Don't coach after the action — just confirm and stop.
- For `push`, parse the date generously: "monday" → next Monday in America/New_York; "+3d" → today + 3 days; ISO date → as-is.
- For `waiting`, populate `waiting_on_what` from task title (heuristic: "Reply re <subject>" → "the reply"; otherwise "the action").
- For `project`, if name doesn't match an existing project, ask once: "No project named '<name>'. Create it? (yes/no)". On yes, create with sensible defaults.
- Never delete a row — `dropped` is the destructive action and it leaves an audit trail.
