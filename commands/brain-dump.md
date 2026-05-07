---
description: Triage a messy brain dump into Delete / Delegate / Defer / Do, with verb-first next actions.
argument-hint: [paste your brain dump, or describe what's in your head]
---

Take whatever the user pasted (or invite them to dump now if they didn't) and run it through the `task-triage-and-prioritization` skill.

**Process:**
1. If the user hasn't pasted anything, prompt: *"Paste it now — typos, fragments, half-thoughts. I'll sort."* Then wait.
2. Sort every item into Delete / Delegate / Defer / Do.
3. Convert Do items into verb-first physical next actions.
4. Tag urgent vs important. Surface projects separately. Surface waiting-ons separately.
5. End with the **single next action** to take in the next 10 minutes.

**Output shape:**

```
DELETE
- ...

DELEGATE → who, what to send
- ...

DEFER → when it returns / where it lives now
- ...

DO — TODAY
- [must]   <verb-first action> (~Xm)
- [should] <verb-first action> (~Xm)
- [could]  <verb-first action> (~Xm)

DO — THIS WEEK
- ...

WAITING ON
- <person/decision> for <what>

PROJECTS (these need their own plan, not just a task)
- <name> → outcome: ... | suggested: run /plan-project

UNRESOLVED
- <thing I need from you to triage further>

NEXT 10 MINUTES
- <one specific action>
```

If the dump has more than ~12 items in "Do today," force a cut and explain why. Wishlists do not survive Tuesdays.

If the user wants the result written to a task manager (Todoist, Things, etc.) and a connector exists, offer to do it. Otherwise output the markdown and stop.
