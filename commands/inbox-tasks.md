---
description: Show ranked email-derived tasks from the Phase 4 brain. Filter by must / should / could / overdue / today / project / sender / @context.
argument-hint: [filter — e.g. "must", "today", "@phone", "from:karen", "project:vitals"]
---

You are showing Dave his Phase 4 inbox-AI tasks ranked by `priority_score`. Read-only — no triage actions in this command. (Use `/inbox-update` to change status.)

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Parse filter

The argument may be:
- empty / "all" → all active tasks (status in todo, doing, waiting)
- "must" / "should" / "could" → priority filter
- "today" → due_date <= CURRENT_DATE OR priority='must'
- "overdue" → due_date < CURRENT_DATE AND status NOT IN ('done','dropped')
- "ymyl" → ymyl_classification IS NOT NULL
- "from:<text>" → sender_email or sender_name ILIKE '%text%'
- "project:<text>" → project name ILIKE '%text%'
- "@<context>" → join task_contexts where context name = '@context'
- "all-time" → include done/dropped too

If filter is unclear, default to "all active" and note it at the top of the output.

## Step 2 — Query

Adjust SQL by filter. Default query:

```sql
SELECT
  t.id, t.title, t.priority,
  t.priority_score,
  t.status,
  t.due_date,
  t.deadline,
  t.ymyl_classification,
  t.sender_name,
  t.sender_email,
  t.source_account,
  t.score_reason,
  p.name AS project_name,
  -- display-time score boost: in final 48h before deadline, ramp to 1.0
  CASE
    WHEN t.deadline IS NOT NULL AND t.deadline > CURRENT_DATE THEN
      LEAST(1.0, t.priority_score + GREATEST(0,
        (1.0 - t.priority_score) * (1.0 - LEAST(48, EXTRACT(EPOCH FROM (t.deadline::timestamp - now()))/3600)/48)))
    ELSE t.priority_score
  END AS display_score,
  -- decay for tasks with no deadline (5%/day, half rate for YMYL)
  CASE
    WHEN t.deadline IS NULL THEN
      GREATEST(0, t.priority_score *
        (1 - (CASE WHEN t.ymyl_classification IS NOT NULL THEN 0.025 ELSE 0.05 END)
          * EXTRACT(EPOCH FROM (now() - t.created_at)) / 86400))
    ELSE t.priority_score
  END AS decayed_score
FROM efc.tasks t
LEFT JOIN efc.projects p ON p.id = t.project_id
WHERE t.status IN ('todo','doing','waiting')   -- adjust per filter
ORDER BY
  CASE WHEN t.ymyl_classification IS NOT NULL THEN 0 ELSE 1 END,  -- YMYL first
  GREATEST(display_score, decayed_score) DESC,
  t.due_date NULLS LAST
LIMIT 25;
```

Also pull a quick total count with the same WHERE so we can show "showing N of M":
```sql
SELECT count(*) FROM efc.tasks WHERE status IN ('todo','doing','waiting');
```

## Step 3 — Output (one screen)

```
🧠 INBOX TASKS — <filter description> (showing N of M)

🔥 YMYL — <count>
  [score] [must|should|could] <title>
        Source: <sender> → <account> | Due: <date or "no deadline">
        Why: <score_reason truncated to 80 chars>
        id: <short uuid>
  ...

⭐ MUST — <count>
  [score] <title>
        Source: <sender> → <account> | Due: <date>
        Why: <score_reason>
        id: <short uuid>
  ...

📥 SHOULD — <count>
  ...

💭 COULD — <count>
  ...

(Run /inbox-show <id> for full email + context. Run /inbox-update <id> done|push|drop|defer to act.)
```

## Rules

- Default sort: YMYL first, then by display-time score (boost+decay applied), then due_date.
- Score format: `0.85` not `0.850000`.
- Show only first 7 chars of UUID (the short ID is enough for /inbox-update to disambiguate).
- Truncate score_reason at 80 chars; full text in `/inbox-show`.
- If a task has no source_email_id (manually captured), label "Source: manual capture".
- If filter returns 0 tasks, say so plainly. No filler.
- One screen total. If many tasks, show top 25; mention how many are hidden.
- Don't coach. Don't add commentary. The user is here to see their queue, not to be pep-talked.
