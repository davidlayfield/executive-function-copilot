---
description: Help the user start a specific task they're avoiding. Lower activation energy and produce a 10-minute launch.
argument-hint: <the task you can't start>
---

The user is stuck on a specific task. Apply the `anti-procrastination-launch` skill.

**Process:**
1. Take the task from the argument. If unclear (e.g., "the thing"), ask **one** clarifying question — what is the task and what does done-enough look like for *this session*.
2. Identify why this might be hard, in one specific sentence (not generic).
3. Produce the launch.

**Output shape:**

```
TASK
- <restated cleanly>

Why this might feel hard
- One sentence. Specific. (Boring? Scary? Unclear? Big? Emotionally loaded?)

Definition of done — for this session
- The lowest bar that still counts. Lower than they expect.

First visible step (under 2 minutes)
- One concrete physical/digital action.

10-minute launch
- Set a timer for 10 minutes. Do this: <specific instruction>.
- When the timer ends, you have permission to stop.

Friction removal — before the timer starts
- [ ] ...
- [ ] ...
- [ ] ...

Body-double / pomodoro option
- I can check in on you at the 10-minute mark — say "check on me" if you want that.
- Or run a 25/5 cycle.

Completion rule
- "Done is better than perfect today." Lower the bar to: <specific lowered bar>.
```

End with one line: *"Ready when you are. Tell me when the 10 minutes start, or just go."*

Do not produce multiple tips, multiple frameworks, or a 30-step plan. One clear launch. That is the deliverable.
