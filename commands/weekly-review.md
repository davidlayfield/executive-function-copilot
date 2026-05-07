---
description: Run a nonjudgmental weekly review. Find patterns, pick 1–2 changes, set 3 outcomes for next week.
argument-hint: [optional summary of the week — paste notes if useful]
---

Apply the `weekly-pattern-review` skill.

**Process:**
1. Gather inputs:
   - Anything the user pasted with this command.
   - The last 5–7 daily plans / shutdowns if they exist as files in the working directory or notes folder.
   - Calendar history for the week if a connector is available.
   - The previous 2–3 weekly reviews if available — to look across weeks, not just inside this one.
   - The `personal-operating-manual.md` if available.
2. If you have nothing, ask **one** question: *"In a few bullets — wins, what got dropped, anything that kept tripping you up?"*

**Output shape:**

```
WEEK OF <date range>

Wins (specific, not generic)
- ...

Dropped balls (without shame)
- <thing>: <one phrase about what got in the way>

Recurring obstacles
- The same thing that derailed me 2+ times.

Best focus windows
- Days/times when work actually happened.

Avoidance themes
- Categories I kept around but didn't touch.

Task-size mismatch
- Tasks that were actually projects in disguise.

Schedule realism (1–5)
- <score>: <one-line why>

Routines
- Keep: ...
- Change: ...
- Remove: ...

Top 3 outcomes for next week
- 1.
- 2.
- 3.

Experiments for next week (small, falsifiable)
- "Try X for 5 days, notice what happens."
```

**Rules:**
- Lead with wins — as data, not cheerleading.
- One or two changes for next week. Not ten.
- If the same obstacle has shown up 3+ weeks running, name it explicitly and propose a structural fix (not "try harder").
- Keep the whole review to one screen.

If the user has a notes folder, offer to save the review as `weekly-review-YYYY-MM-DD.md`. Otherwise output as a single markdown block.

If the review surfaces something durable (e.g., "I am consistently overcommitted on Mondays"), propose 1–2 lines for the `personal-operating-manual.md`. Show the diff. Wait for approval.
