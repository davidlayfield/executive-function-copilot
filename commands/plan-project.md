---
description: Turn a project too big to hold in your head into outcome, milestones, next actions, dependencies, and a 10-minute starter task.
argument-hint: <project name or short description>
---

Apply `task-triage-and-prioritization` and `executive-function-coaching`.

**Process:**
1. Take the project from the argument. If unclear, ask **one** question: *"What's the desired outcome, in one sentence?"*
2. Build the smallest plan that lets the user start *today*. A project plan is not a Gantt chart; it is permission to begin.

**Output shape:**

```
PROJECT: <name>

Outcome (one sentence)
- What "done" looks like, in user-visible terms.

Constraints
- Deadline: ...
- Budget: ...
- Other (people, dependencies, energy):

Milestones (3–5, no more)
- M1: ...
- M2: ...
- M3: ...

Next actions (verb-first, ordered, ~5 max for the active milestone)
- [ ] ...
- [ ] ...

Dependencies / Waiting on
- <person/decision/info> for <what>

Decisions to make
- ...

Risks (the 1–3 things most likely to derail this)
- <risk>: <one-line mitigation>

10-minute starter task
- The single thing to do right now to make the project real.

Recurring review cadence
- Weekly / biweekly / monthly. When and where.
```

**Rules:**
- 3–5 milestones, never more. If it needs more, the project is actually a portfolio — name that.
- Active-milestone next actions only. Do not pre-plan future milestones in detail.
- Every dependency or waiting-on item gets a name and a request.
- The 10-minute starter must be visible-progress (a file created, a draft started, a question sent), not "plan more."

If the user has a notes folder, offer to save the plan as `project-<slug>.md`. Otherwise output as one markdown block.
