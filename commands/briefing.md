---
description: Morning briefing — read inbox, overdue tasks, and the operating manual; produce a small realistic plan and the digest of new captures.
argument-hint: [optional notes about today — energy, deadlines, constraints]
---

Run Dave's morning briefing. This is the daily ritual that replaces /daily-plan in the DB-backed system. It does three things in one pass: surface what came in overnight, propose a small plan, ask the digest decisions.

**Step 1 — Read the operating manual** (always; it changes how you coach).

```sql
SELECT content FROM efc.operating_manual WHERE is_current = true LIMIT 1;
```

Honor everything in the manual. The "Rules for Claude when coaching me" section is non-optional.

**Step 2 — Pull state from Supabase** (project_id `psmkklhyfkivyokhaiga`). Run these in one go:

```sql
-- Pending inbox count + recent captures
SELECT id, source, raw_text, extracted_action_item, captured_at, openbrain_memory_id
FROM efc.inbox_items
WHERE status = 'pending'
ORDER BY captured_at DESC
LIMIT 15;

-- Overdue and due-today tasks
SELECT t.id, t.title, t.due_date, t.priority, t.status, p.name AS project
FROM efc.tasks t
LEFT JOIN efc.projects p ON p.id = t.project_id
WHERE t.status IN ('todo','doing','waiting')
  AND (t.due_date <= CURRENT_DATE OR t.priority = 'must')
ORDER BY t.due_date NULLS LAST, t.priority;

-- Top-of-mind projects (heaviest weight, recently touched)
SELECT id, name, desired_outcome, weight, last_touched_at
FROM efc.projects
WHERE status = 'active'
ORDER BY weight DESC NULLS LAST, last_touched_at DESC NULLS LAST
LIMIT 5;
```

**Step 3 — Honor the time context.** The UserPromptSubmit hook injects current time + window. If we're in the **CRASH window**, halve the plan size and lead with recovery. If we're in **PEAK**, make sure the must-do is something that uses the window (real thinking, not admin). If we're outside Dave's working hours, ask once whether he's planning for now or for tomorrow.

**Step 4 — Output (this exact shape, one screen):**

```
BRIEFING — <date>, <day>, <time-window>

Anchor goal
- One sentence. The thing that, if done, makes today a win.

Must (1)
- <verb-first action> — task id <id> or new

Should (up to 2)
- ...

Could (up to 3)
- ...

First 10-minute action
- The single thing to do right now. Smaller than feels reasonable.

If I fall behind today
- Minimum-viable version: <the 1 thing that still has to happen>.

INBOX — <N> new since last briefing
- 1. [<source>] <text snippet>  → keep / drop / done?
- 2. ...
- (Up to 10. If more, say so and offer a /triage pass.)

OVERDUE — <N>
- <title> (was due <date>)  → push to <date> / drop / done?
- ...

Pattern note (only if real)
- One sentence about a recurring obstacle, scope creep, "loudest thing wins" pattern, or anything from the manual that today's data is showing. Skip if there's nothing real to say.
```

**Step 5 — Save the plan** to `efc.daily_plans` so /shutdown can read it later:

```sql
INSERT INTO efc.daily_plans (
  plan_date, anchor_goal, must_task_ids, should_task_ids, could_task_ids,
  ten_min_action, recovery_plan, generated_from_text
)
VALUES (
  CURRENT_DATE, '<anchor_goal>',
  ARRAY['<uuid>']::uuid[], ARRAY[...]::uuid[], ARRAY[...]::uuid[],
  '<10-min action>', '<recovery>', $G$<any user notes>$G$
)
ON CONFLICT (plan_date) DO UPDATE SET
  anchor_goal = EXCLUDED.anchor_goal,
  must_task_ids = EXCLUDED.must_task_ids,
  should_task_ids = EXCLUDED.should_task_ids,
  could_task_ids = EXCLUDED.could_task_ids,
  ten_min_action = EXCLUDED.ten_min_action,
  recovery_plan = EXCLUDED.recovery_plan,
  generated_at = now();
```

**Rules:**
- Do not produce a 2,000-word briefing. One screen.
- Do not list every overdue task — show the top 5–8 most relevant. Hide tail behind a count.
- The daily-digest decisions (keep/drop/done/push) are presented but **not auto-acted**; wait for Dave's reply, then run the appropriate updates.
- Honor the warm-up tax. If Dave just got into the chair, the first 10-minute action should be a soft start, not a heavy task.
- If the operating manual surfaces a pattern that today's data confirms (e.g., 3+ items deferred from "@home" context, suggesting weekend-evening overload) — name it, briefly, once.
- If something points beyond coaching (per the manual's "What I am and am not" rule) — note it as something worth raising with Dave's therapist or doctor. Do not diagnose.
