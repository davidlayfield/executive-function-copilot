---
name: personal-operating-manual
description: Maintain the user's living personal-operating-manual.md — a file capturing how they work best, what derails them, and rules for how the assistant should coach them. Use whenever planning, debriefing, or learning something durable about the user.
---

# Personal Operating Manual

The operating manual is the assistant's memory of how this user actually works. Without it, every session starts from zero.

## File location

Default to `personal-operating-manual.md` in the current working directory. If the user has pointed at a notes folder (Obsidian vault, iCloud notes folder, etc.), put it there. Always tell the user where it lives. Never silently move it.

## Sections

```markdown
# Personal Operating Manual — <name>

## My best work conditions
- Best windows of the day:
- Best environment:
- Tools that actually help:

## My common derailers
- Things that consistently kill momentum:

## Tasks I avoid and why
- <task category>: <reason — boredom, fear, unclear, emotional load, perfectionism>

## What helps me start
- ...

## What does not help me
- ...

## Reminder preferences
- Channels I act on (calendar, paper, app, partner, none):
- Channels I ignore:
- Cadence that works:

## Planning preferences
- Plan size that I will actually execute:
- Format I prefer:
- How much detail before it becomes noise:

## Communication preferences
- How I want feedback:
- What I do not want (lecturing, options paralysis, etc.):

## Energy patterns
- Days/times I have energy:
- Days/times I usually crash:
- Recovery activities that work:

## Recovery plans
- After a missed day:
- After a missed week:
- After a hard month:

## Weekly review insights (rolling)
- <date>: <one-sentence pattern>

## Rules for Claude when coaching me
- ...
```

## How to update

- After any meaningful exchange where you learn something durable about the user, propose 1–3 lines to add. Show the diff. Wait for approval before writing.
- Never write to the manual without showing the change first.
- Keep entries short and concrete. "I avoid email after lunch" beats "I struggle with email-related task initiation in the post-prandial window."
- Prune. If a line has been contradicted by behavior for several weeks, propose removing it.

## Privacy

- Do not store sensitive personal-health details (diagnoses, medications, mental-health history) unless the user explicitly asks.
- Do not store anything the user has marked as private to a specific conversation.
- The manual lives on the user's machine or chosen storage. The assistant does not transmit it elsewhere.

## When to suggest building one

If the user has run two or more planning, brain-dump, or weekly-review sessions and no manual exists, suggest creating one: *"I'd remember more about how you work if we kept a short operating manual. Want me to start one?"*
