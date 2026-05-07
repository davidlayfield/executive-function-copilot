---
description: Build a realistic plan for today — anchor goal, must/should/could, first 10-minute action, recovery plan.
argument-hint: [optional brain dump, energy level, deadlines]
---

Run a daily planning workflow.

**Inputs to use:**
- Anything the user pasted with this command (brain dump, current energy, known deadlines, constraints).
- The user's calendar, task list, and notes if MCP connectors are available — pull what is relevant, don't dump it all.
- The user's `personal-operating-manual.md` if it exists in the working directory or a known notes location. Honor stated best work windows, derailers, and "rules for Claude when coaching me."

**Process:**
1. If essential context is missing (e.g., no idea what's on the user's plate), ask **one** clarifying question. Otherwise proceed with reasonable defaults and let them correct.
2. Apply the `executive-function-coaching` and `task-triage-and-prioritization` skills.

**Output (this exact shape):**

```
TODAY — <date, day of week>

Anchor goal
- One sentence. The thing that, if done, makes today a win.

Must (1)
- <verb-first action> (~Xm)

Should (up to 2)
- <verb-first action> (~Xm)
- <verb-first action> (~Xm)

Could (up to 3)
- ...

First 10-minute action
- The single thing to do right now. Smaller than feels reasonable.

Time blocks (rough)
- <block>: <activity>
- <block>: <activity>

Anti-avoidance notes
- The task most likely to be skipped today, and one specific friction-removal step.

Mid-day check-in prompt
- A short question to ask yourself at <time>.

If I fall behind
- The minimum-viable version of today. The 1 thing that still needs to happen.

End-of-day shutdown
- Reminder to run /shutdown at <time>.
```

Keep the whole plan to one screen. If it doesn't fit, the plan is too big — cut.
