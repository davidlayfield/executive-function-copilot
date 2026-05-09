---
description: Show all tasks in waiting status — who you're waiting on, how long, and which ones the chase routine has flagged for nudge or hard-chase. Phase 4 M3.
argument-hint: [list|stale|nudged|chased]
---

Show Dave's waiting tasks — the silent backlog of "ball is in someone else's court" items. Default behavior: list everything `status='waiting'` with how many days each has been waiting, plus chase state.

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Sub-commands

- `(no arg)` or `list` — all waiting tasks, sorted oldest first
- `stale` — only tasks waiting > 3 days
- `nudged` — only tasks where the 3-day soft nudge has fired
- `chased` — only tasks where the 7-day hard chase has fired (now back in todo)

## Step 1 — Pull rows

```sql
-- list / default
SELECT t.id, t.title, t.waiting_on_person, t.waiting_on_what,
       t.waiting_since,
       EXTRACT(DAY FROM (now() - t.waiting_since))::int AS days_waiting,
       t.chase_nudged_at, t.chased_at,
       t.priority, t.priority_score,
       t.sender_email, t.source_account, t.thread_id,
       p.name AS project_name
FROM efc.tasks t
LEFT JOIN efc.projects p ON p.id = t.project_id
WHERE t.status = 'waiting'
ORDER BY t.waiting_since NULLS LAST, t.priority_score DESC NULLS LAST;

-- stale (waiting > 3 days)
-- ... add: AND waiting_since < now() - interval '3 days'

-- nudged
-- ... add: AND chase_nudged_at IS NOT NULL

-- chased (now back in todo, but historically chased — different status filter)
SELECT t.id, t.title, t.waiting_on_person, t.chased_at,
       EXTRACT(DAY FROM (now() - t.chased_at))::int AS days_since_chase,
       t.status, t.priority
FROM efc.tasks t
WHERE t.chased_at IS NOT NULL
  AND t.chased_at > now() - interval '14 days'
ORDER BY t.chased_at DESC;
```

## Step 2 — Output

If no rows → `Nothing waiting. Inbox-side, you're clear.`

Otherwise a compact table. ONE row per task. Sort oldest first.

```
WAITING TASKS — N total

DAYS  WAITING ON       WHAT                            STATE       TASK
────  ──────────────   ─────────────────────────────   ─────────   ──────────────────────────
  9d  Tom Ayd          confirm CAHEC sponsor sign-off  CHASED      Decide on CAHEC sponsorship
  5d  Charlie Moore    Q1 financials draft             nudged 2d   Review Q1 close packet
  2d  Josh Cappell     PRD review                                  Send Vitals PRD to engineering
  0d  Juliana          dinner plan Sat                             Reply re: weekend
```

State column legend (only show legend if non-empty in output):
- `(blank)` — fresh wait, < 3 days
- `nudged Nd` — 3-day soft nudge fired N days ago, surfaced in morning brief
- `CHASED` — 7-day hard chase fired (task is now back in todo with title prefix)

## Step 3 — Decision prompt

End the output with:

```
Reply to push, drop, or chase. Or say 'all good' to leave them.

Common patterns:
- "drop 1, push 2 to monday, chase 3"
- "everything < 3 days is fine"
- "chase Tom about CAHEC"
```

## Rules

- Don't auto-chase from this command — it's a viewer. Use `/inbox-update <id> done|drop|push|...` for action.
- Show waiting_on_person and waiting_on_what — those are what make the row legible. Truncate WHAT to ~30 chars.
- Sort by `waiting_since ASC` (oldest first) — Dave should see the longest-waiting at the top.
- If a task is both `chase_nudged_at` AND `chased_at` set, prefer `CHASED` label (more recent state).
- Cap output at 30 rows. If more, show top 30 + "and K more — /inbox-waiting all to see all".
