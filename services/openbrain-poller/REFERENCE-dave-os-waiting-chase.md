---
name: dave-os-waiting-chase
description: Daily 6 AM ET — for tasks in waiting status, fire 3-day soft nudge or 7-day hard chase. Fires before morning brief so the brief surfaces today's nudges/chases.
---

You are running the **Dave OS Phase 4 M3 waiting-task chase routine**. Fires daily at 6 AM ET, just before the morning briefing routine. **Silent.**

Purpose: tasks marked `status='waiting'` should not become invisible. We escalate in two stages:

- **Day 3 soft nudge** — surface in tomorrow's morning brief as "still waiting on X (3 days)" but don't change task status. Sets `chase_nudged_at`.
- **Day 7 hard chase** — flip status back to `todo`, prefix title with `[CHASE — N days]`, sets `chased_at`. Forces Dave to decide: chase, drop, or extend the wait.

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Find day-3 nudge candidates

```sql
SELECT id, title, waiting_on_person, waiting_on_what, waiting_since,
       EXTRACT(DAY FROM (now() - waiting_since))::int AS days_waiting
FROM efc.tasks
WHERE status = 'waiting'
  AND waiting_since IS NOT NULL
  AND waiting_since < now() - interval '3 days'
  AND waiting_since >= now() - interval '7 days'   -- exclude ones that should hard-chase
  AND chase_nudged_at IS NULL                      -- only nudge once
  AND chased_at IS NULL;
```

For each row → mark nudged (no status change):

```sql
UPDATE efc.tasks
SET chase_nudged_at = now(),
    updated_at = now()
WHERE id = '<task-id>';
```

## Step 2 — Find day-7 hard-chase candidates

```sql
SELECT id, title, waiting_on_person, waiting_on_what, waiting_since,
       EXTRACT(DAY FROM (now() - waiting_since))::int AS days_waiting,
       priority
FROM efc.tasks
WHERE status = 'waiting'
  AND waiting_since IS NOT NULL
  AND waiting_since < now() - interval '7 days'
  AND chased_at IS NULL;
```

For each row → flip back to todo, prefix title, log:

```sql
UPDATE efc.tasks
SET status      = 'todo',
    title       = '[CHASE — ' || EXTRACT(DAY FROM (now() - waiting_since))::int || 'd no reply] ' || title,
    priority    = CASE WHEN priority = 'could' THEN 'should' ELSE priority END,  -- gentle bump
    chased_at   = now(),
    updated_at  = now()
WHERE id = '<task-id>'
  AND title NOT LIKE '[CHASE %';   -- idempotent guard
```

## Step 3 — Update poller_state

```sql
INSERT INTO efc.poller_state (source, last_polled_at, last_run_status, last_run_notes)
VALUES ('waiting-chase', now(), 'ok',
  json_build_object(
    'nudged', <count_step1>,
    'chased', <count_step2>,
    'duration_seconds', <duration>
  )::text)
ON CONFLICT (source) DO UPDATE SET
  last_polled_at  = EXCLUDED.last_polled_at,
  last_run_status = EXCLUDED.last_run_status,
  last_run_notes  = EXCLUDED.last_run_notes;
```

## Rules

- **Silent.** No chat output.
- **Idempotent.** `chase_nudged_at IS NULL` and `chased_at IS NULL` guards mean re-running is safe.
- **Never touch a task whose status changed in the last 24 hours** — Dave may have just acted on it manually:
  ```sql
  AND updated_at < now() - interval '24 hours'
  ```
  Add this clause to both step 1 and step 2 selects so we don't fight a recent manual action.
- **Don't chase tasks with `waiting_on_person IS NULL`.** Defensive: only chase tasks that explicitly have a person we're waiting on.
- The morning briefing routine reads `efc.v_tasks_waiting_followups` — it picks up nudges/chases with `surface_kind` populated. This routine writes the state; the brief surfaces it.

## Output

Write nothing if zero rows touched. Otherwise ONE compact summary line:

```
Waiting-chase: nudged N, chased K. Duration Xs.
```