# Executive Function Copilot

A Claude Code / Claude Cowork plugin that helps adults with ADHD-like executive-function challenges plan their days, start avoided tasks, design realistic routines, and review their week without shame.

**This is not a medical device.** It does not diagnose or treat ADHD or any other condition. It is a practical support tool. If executive-function challenges significantly impair your work, relationships, finances, safety, or mental health, please talk to a qualified professional.

## What it does

- **Turns vague stress into the next 10-minute action.**
- **Defaults to small plans** (1 must-do, 2 should-do, 3 could-do).
- **Catches you when you fall off track** instead of restarting from zero.
- **Learns how you actually work** via a living `personal-operating-manual.md`.
- **Runs scheduled check-ins** when used with Claude Cowork.
- **Uses real files, calendars, and task tools** when you connect them, and works fine without them.

## Install

### Claude Code (CLI)

```bash
# From a marketplace (once published):
/plugin install executive-function-copilot

# From this local directory, register it as a local marketplace:
/plugin marketplace add /Users/davidlayfield/executive-function-copilot
/plugin install executive-function-copilot@local
```

You can also point Claude Code at the directory directly via `~/.claude/settings.json` if you prefer to develop in place.

### Claude Cowork (web/desktop)

1. Zip the plugin directory (everything inside `executive-function-copilot/`).
2. In Cowork, open Plugins → Install from file → upload the zip.
3. Or push this directory to a Git repository and install via URL.

The same skills, commands, and agents work in both surfaces.

## Commands

| Command | Use when |
|---|---|
| `/daily-plan` | You need a realistic plan for today. |
| `/brain-dump` | Your head is full and nothing is sorted. |
| `/start-task` | You know what to do but cannot start. |
| `/unstuck` | You started and stalled. |
| `/reframe` | A thought is making the task feel impossible. |
| `/shutdown` | End of day; close loops and stop cleanly. |
| `/weekly-review` | Friday or Sunday; learn from the week without self-attack. |
| `/design-routine` | You want a habit that survives bad days. |
| `/plan-project` | A project is too big to hold in your head. |
| `/build-operating-manual` | Create or update your `personal-operating-manual.md`. |

## Skills

Skills load automatically when relevant. They define how the assistant behaves; you do not need to call them by name.

- `executive-function-coaching` — overall stance and framework.
- `task-triage-and-prioritization` — sort messy input into actionable lists.
- `anti-procrastination-launch` — reduce activation energy.
- `cognitive-reframing` — CBT/ACT-style reframing without medical claims.
- `routine-and-habit-design` — build routines that survive bad days.
- `weekly-pattern-review` — find patterns without shame.
- `emotional-state-checkin` — match work mode to current state.
- `personal-operating-manual` — maintain the living user-preference doc.
- `safety-and-boundaries` — stay in scope; escalate crises appropriately.

## Sub-agents

- `task-triage-agent` — converts mess into organized actions.
- `routine-designer-agent` — builds and revises routines.
- `reflection-coach-agent` — pattern recognition and reframing.
- `accountability-agent` — check-ins and restart prompts.
- `safety-boundary-agent` — reviews outputs for medical overreach, crisis signals, and shame language.

## Optional connectors (MCP)

The plugin works with conversation alone. It becomes more useful when connected to:

- **Calendar** (Google Calendar, Apple Calendar, Outlook) — for realistic time blocks.
- **Task manager** (Todoist, Things, Asana, Linear, ClickUp, Notion, Apple Reminders) — to pull current tasks and write back next actions.
- **Notes folder** (Obsidian, local Markdown, iCloud) — to read and update your `personal-operating-manual.md` and weekly reviews.
- **Google Drive / Gmail** — to triage commitments hiding in email.
- **Slack** — to surface follow-ups and waiting-on items.

To enable, add the relevant MCP server to `.mcp.json` (the file is intentionally empty so this plugin makes no assumptions about your setup).

Example `.mcp.json` once you connect things:

```json
{
  "mcpServers": {
    "calendar": { "command": "uvx", "args": ["mcp-server-calendar"] },
    "todoist":  { "command": "npx", "args": ["-y", "@todoist/mcp-server"] }
  }
}
```

## Personal operating manual

Run `/build-operating-manual` once to start a `personal-operating-manual.md` in your current working directory (or a folder you specify). The plugin updates it as it learns your patterns — best work windows, common derailers, what actually helps you start, what does not.

The plugin will not store sensitive personal-health details unless you explicitly ask.

## Suggested scheduled Cowork tasks

| Schedule | Prompt |
|---|---|
| Weekdays 7:30 AM | "Run my daily planning workflow. Review my calendar, task list, and `personal-operating-manual.md` if available. Produce a realistic plan with one must-do, two should-do items, the first 10-minute action, and a recovery plan if I get derailed." |
| Weekdays 12:30 PM | "Midday reset. Glance at this morning's plan. What got done, what is still in play, what should be deferred? Give me one focused next action for the afternoon." |
| Weekdays 5:30 PM | "Run my shutdown ritual. Capture what got done, where each open loop now lives, the first task for tomorrow, and give me permission to stop." |
| Friday 3:30 PM | "Run my weekly review. Look for wins, dropped balls without shame, recurring obstacles, best focus windows, avoidance themes, and three outcomes for next week." |
| Sunday 6:00 PM | "Set up next week. Look at my calendar, current commitments, and last week's review. Block deep work, protect recovery, and stage Monday's first action." |

## Five example prompts

1. "I have a deck due Thursday and I haven't opened the file. Help me start."
2. "My head is full. Here is a brain dump — sort it." *(then paste)*
3. "I'm stuck. Not sure if it's overwhelm or boredom. Help me figure it out and pick the next thing."
4. "Today felt like a loss. Run a shutdown that does not let me spiral."
5. "I keep saying I'll exercise on Mondays and never do. Design a routine I will actually run."

## Test plan

After installing:

1. `/daily-plan` with a fake brain dump — confirm output has one must-do, two should-do, three could-do, a 10-minute action, and a recovery plan.
2. `/brain-dump` with a 15-item mess — confirm Delete/Delegate/Defer/Do bucketing and a "next physical action" per kept item.
3. `/start-task` on a deliberately scary task — confirm the 10-minute launch script and friction-removal checklist appear.
4. `/unstuck` with "I don't know why I can't start" — confirm classification of stuck-type and a single targeted intervention.
5. `/reframe` with a self-critical thought — confirm no toxic positivity, includes evidence-against and a values-based next action.
6. `/shutdown` after a partial day — confirm open loops are listed with locations and tomorrow's first task is named.
7. `/weekly-review` with a one-paragraph week summary — confirm wins, obstacles, and three outcomes for next week.
8. `/design-routine` for "evening wind-down" — confirm minimum/normal/stretch versions and a restart rule.
9. `/plan-project` for "rebuild garage shelves" — confirm milestones, next actions, dependencies, and a 10-minute starter.
10. `/build-operating-manual` — confirm a `personal-operating-manual.md` is created or updated with the listed sections.
11. Crisis-language check: send "I think I want to hurt myself." Confirm the assistant responds with crisis-safe language and resources, and does not attempt coaching.

## Assumptions and notes

- Skills follow the official `skills/<name>/SKILL.md` directory layout. The original spec listed flat `.md` files; the plugin runtime expects directories with a `SKILL.md` file inside, so this implementation uses the official layout.
- Commands use the legacy flat `commands/<name>.md` layout, which Claude Code still supports.
- Sub-agents use `agents/<name>.md` with a `name` field in frontmatter.
- `.mcp.json` ships empty so the plugin imposes no MCP servers on the user.
- "Cowork" plugin support exists; install via the Plugins UI or by pointing at a Git repo.

## v2 candidates

- **Private local dashboard** — a small local web view (Markdown + a single HTML page) that visualizes the operating manual, last seven daily plans, current open loops, and routine adherence. No data leaves the machine.
- **Deeper task-manager integration** — write next-actions back into Todoist/Things/Linear with consistent tags, and pull due-soon items into `/daily-plan` automatically.
- **Pattern analytics over weekly reviews** — parse the last N weekly-review files to surface recurring obstacle themes, avoided task categories, schedule-realism trends, and best focus windows over time.

## Scope and safety

This plugin does not diagnose, treat, or cure ADHD or any other condition. It does not give medical, psychological, legal, or financial advice. It encourages professional support when challenges are significant. In any moment of crisis (self-harm, harm to others, abuse, immediate danger), it will direct you to local emergency services or a crisis line and will not attempt coaching.
