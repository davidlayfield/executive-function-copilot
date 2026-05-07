---
description: Create or update your personal-operating-manual.md — a living file of how you work, what derails you, and how Claude should coach you.
argument-hint: [optional path or notes folder]
---

Apply the `personal-operating-manual` skill.

**Process:**
1. Determine where the file lives:
   - If the user named a path in the argument, use it.
   - Else default to `personal-operating-manual.md` in the current working directory.
   - Tell the user the path before you write.
2. Check whether a manual already exists at that path.
   - **If yes:** read it, then walk the user through updating each section briefly. For each section, ask: *"Anything to change here?"* Skip if no answer in a few seconds; do not interrogate.
   - **If no:** create it from the template below. Ask the user the section questions one at a time, in a calm voice, and accept "skip" as a valid answer for any of them.
3. Write the file. Show the diff before saving.

**Template:**

```markdown
# Personal Operating Manual — <name>

## My best work conditions
- Best windows of the day:
- Best environment:
- Tools that actually help:

## My common derailers
- ...

## Tasks I avoid and why
- <category>: <reason>

## What helps me start
- ...

## What does not help me
- ...

## Reminder preferences
- Channels I act on:
- Channels I ignore:
- Cadence that works:

## Planning preferences
- Plan size that I will actually execute:
- Format I prefer:
- How much detail before it becomes noise:

## Communication preferences
- How I want feedback:
- What I do not want:

## Energy patterns
- Days/times I have energy:
- Days/times I usually crash:
- Recovery activities that work:

## Recovery plans
- After a missed day:
- After a missed week:
- After a hard month:

## Weekly review insights (rolling)
- (added by the assistant after each weekly review)

## Rules for Claude when coaching me
- ...
```

**Rules:**
- Ask the section questions sparingly. The user can fill in blanks themselves later. Do not run a 30-question intake.
- Keep entries concrete and short. "I avoid email after lunch" beats long descriptions.
- Do not record sensitive personal-health details (diagnoses, medications, mental-health history) unless the user explicitly asks.
- Always show the diff before writing or updating.
- After saving, tell the user where the file lives and how to update it later (run this command again, or just say "add to my operating manual: ...").
