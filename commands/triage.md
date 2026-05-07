---
description: Process the EFC inbox — turn captured items into projects/tasks, drop noise, defer the rest.
argument-hint: [optional limit, default all pending]
---

Walk Dave through processing his EFC inbox using GTD discipline. Each item gets ONE decision: drop, defer, delegate, do (turn into a task in a project).

**Step 1 — Pull state.** Run via supabase MCP, project `psmkklhyfkivyokhaiga`:

```sql
SELECT id, source, raw_text, extracted_action_item, captured_at, openbrain_memory_id, source_metadata
FROM efc.inbox_items
WHERE status = 'pending'
ORDER BY captured_at ASC
LIMIT 30;  -- batch process

SELECT id, name, area_id FROM efc.projects WHERE status='active' ORDER BY name;
SELECT id, name FROM efc.areas_of_focus WHERE status='active' ORDER BY name;
SELECT id, name FROM efc.contexts ORDER BY name;
```

If inbox is empty, say so and stop.

**Step 2 — Process each item.** For each row, present:

```
[i/N] <source> <relative captured_at>
"<raw text or extracted_action_item, full but trimmed at 200 chars>"

Suggested:
  Action: do / defer / delegate / drop / waiting
  If do → Project: <best match from active list, or "new: <suggested name>">
          Title (verb-first): <suggested>
          Contexts: <best matches, e.g. @phone @errand>
          Energy: low/medium/high
          Estimate: <minutes>
```

Wait for Dave's response. He can:
- Accept the suggestion (`ok` / `yes` / silence)
- Override anything (`new project Sprinklers`, `context @repair @weekend`, `defer to Saturday`, `drop`, etc.)
- Skip (`skip` / `next`)

**Step 3 — Apply the decision** with the right SQL:

- **Drop:**
  ```sql
  UPDATE efc.inbox_items SET status='dropped', triaged_at=now()
  WHERE id = '<id>';
  ```

- **Defer:** create a deferred task, link back.
  ```sql
  WITH t AS (
    INSERT INTO efc.tasks (project_id, title, status, deferred_until, openbrain_memory_id, external_source, external_id, notes)
    VALUES (<project_id_or_null>, '<title>', 'deferred', '<date>', <openbrain_id>, 'manual', NULL, NULL)
    RETURNING id
  )
  UPDATE efc.inbox_items SET status='triaged', triaged_at=now(), triaged_to_task_id=(SELECT id FROM t)
  WHERE id = '<inbox_id>';
  ```

- **Delegate / waiting:** create a `waiting` task with `waiting_on_person` and `waiting_on_what`.

- **Do:** create the task. If new project, create that first. Attach contexts.
  ```sql
  -- new project (if needed)
  INSERT INTO efc.projects (area_id, name, desired_outcome) VALUES (...) RETURNING id;
  -- task
  INSERT INTO efc.tasks (project_id, title, priority, energy_required, time_estimate_min, openbrain_memory_id)
  VALUES (...) RETURNING id;
  -- contexts (M2M)
  INSERT INTO efc.task_contexts (task_id, context_id)
  SELECT '<task_id>', id FROM efc.contexts WHERE name = ANY(ARRAY['@phone','@errand']);
  -- mark inbox triaged
  UPDATE efc.inbox_items SET status='triaged', triaged_at=now(), triaged_to_task_id='<task_id>'
  WHERE id = '<inbox_id>';
  ```

**Step 4 — Summary at the end.**

```
TRIAGE COMPLETE

Processed: N items
- Done:      <count>
- New tasks: <count> across <P> projects
- Deferred:  <count>
- Delegated: <count>
- Dropped:   <count>

New active projects (if any): <list>

Still pending: <count> (run /triage again to continue)
```

**Rules:**
- Default to **suggesting**, not autopiloting. Dave decides; you propose.
- Verb-first task titles. "Email Karen the policy number" not "Karen / insurance."
- If the inbox item came from OpenBrain, **always carry forward** `openbrain_memory_id` to the resulting task — that's the trace back to the call/email/chat where it originated.
- Don't try to triage 50 items in one pass. Default batch is 30; offer to stop after 10 if Dave seems fatigued.
- If something feels like a project (more than one task to reach the outcome), create the project + the next-action task. Don't shoehorn projects into single tasks.
- If a captured item is a duplicate of an existing active task, **don't create a new one** — link the inbox to the existing task and mark triaged. Detect by similarity of title + project.
- Counter scope creep: if Dave wants to add a third sub-task to a 2-task project mid-triage, push back. Triage = sort, not plan.
