# Executive Function Copilot

A Claude Code / Claude Cowork plugin that's growing into a personal operating system — captures, organizes, and reflects on Dave's actions, thoughts, observations, and interactions, then coaches him on what to do today and what's drifting over weeks and years.

Built around GTD orthodoxy (David Allen) for adults with ADHD-like executive-function challenges. Storage in Supabase. Optional cross-machine fleet support (Main Mac, Ralph, HomeBase, LittleMac, Walli).

**This is not a medical device.** It does not diagnose, prescribe, or treat any condition. It _is_ a high-level coach for organization, planning, and getting things done — and it surfaces patterns that may be worth raising with a real clinician.

For the full architecture, schema, and phase plan, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
For the version history, see [`CHANGELOG.md`](CHANGELOG.md).

## What it does today (v0.3.0)

- **`/capture`** — frictionless GTD capture into a Supabase inbox.
- **`/journal`** — log a state observation (mood, body, food, medication, energy, relationships) — distinct from action items.
- **`/inbox`** — show pending captures.
- **`/triage`** — walk the inbox GTD-style (do / defer / delegate / drop / waiting / journal), suggesting project / contexts / energy / time-estimate per item.
- **`/briefing`** — morning brief that reads inbox + overdues + active projects + operating manual + time-context, then produces a one-screen plan.
- **`/shutdown`**, **`/weekly-review`**, **`/design-routine`**, **`/plan-project`**, **`/build-operating-manual`**, **`/unstuck`**, **`/reframe`**, **`/start-task`**, **`/brain-dump`**, **`/daily-plan`** — conversational coaching surfaces, some still pre-Supabase.

15 plugin commands. 9 skills. 5 sub-agents. 4 examples.

## What it's growing into

A four-layer system. Currently L1 + L2 are real; L3 + parts of L4 are next.

- **L1 — Firehose.** OpenBrain ingests Gmail, Fireflies, ChatGPT/Claude, GChat, YouTube, briefings — 188k+ memories.
- **L2 — Structured personal data.** `efc.*` schema in Supabase: 15 tables for projects, tasks, contexts, inbox, journal entries, people, interactions, reflections, the versioned operating manual.
- **L3 — Autonomous reflection.** Nightly cron on Ralph reads today's L2, compares to last week / month / year, writes a `daily_reflections` row. (Not yet built.)
- **L4 — Coaching surface.** The plugin commands above, honoring Dave's operating manual and the time-context hook ("now is your peak window" / "now is the crash window").

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for diagrams and schema.

## Install

### Prerequisites

- **Claude Code CLI** ≥ 2.1.x (or **Claude Cowork** desktop app — same plugin works in both).
- **Supabase** project for the `efc.*` schema. The development project is `clawd-context` (ID `psmkklhyfkivyokhaiga`); other deployments need their own.
- **Anthropic API key** is not required for the plugin itself, but is for the OpenBrain poller's fallback extractor (Phase 1.C, not yet on).

### Install in Claude Code (local marketplace)

```bash
claude plugin marketplace add /path/to/executive-function-copilot
claude plugin install executive-function-copilot@executive-function-copilot
```

Or from this GitHub repo directly:

```bash
claude plugin marketplace add https://github.com/davidlayfield/executive-function-copilot
claude plugin install executive-function-copilot@executive-function-copilot
```

Then restart Claude Code (or Cmd+Q the desktop app and relaunch). Slash commands appear namespaced as `/executive-function-copilot:<name>`.

### Apply the schema migrations

The repo's migrations live in this README and `docs/ARCHITECTURE.md`; full SQL is also in the project's Supabase migration history. To bootstrap a fresh project:

1. Create a Supabase project.
2. Apply the migrations in order (see `docs/ARCHITECTURE.md` § Schemas).
3. Add `efc` (and `openbrain` if you're using it) to the PostgREST exposed schemas:

   ```sql
   ALTER ROLE authenticator SET pgrst.db_schemas TO 'public, graphql_public, efc, openbrain';
   NOTIFY pgrst, 'reload schema';
   ```

4. Grant access to roles:

   ```sql
   GRANT USAGE ON SCHEMA efc TO anon, authenticated, service_role;
   GRANT ALL ON ALL TABLES IN SCHEMA efc TO service_role, authenticated;
   ALTER DEFAULT PRIVILEGES IN SCHEMA efc GRANT ALL ON TABLES TO service_role, authenticated;
   ```

5. Insert your operating manual into `efc.operating_manual` (version 1, `is_current = true`).

### Install the time-context hook

`~/.claude/hooks/time-context.sh` injects current time + Dave's energy-window into every Claude prompt. Register it in `~/.claude/settings.json` under `hooks.UserPromptSubmit`. The hook script lives in this repo (or copy from `services/openbrain-poller/`'s sibling pattern; see `docs/ARCHITECTURE.md` § Time-context awareness).

### Deploy the OpenBrain poller (optional, recommended)

For autonomous capture from Gmail, calls, AI sessions, etc., deploy the poller to a long-lived machine (Ralph in this fleet):

```bash
cd services/openbrain-poller
export SUPABASE_URL="https://<project>.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="<service role key>"
bash deploy-to-ralph.sh
```

Status: deployed but **timer not enabled** until OpenBrain's own `action_items` extraction is producing reliably. See `services/openbrain-poller/README.md`.

## Usage

After install + restart, in any Claude Code or Cowork session:

```
/executive-function-copilot:capture quick thought, send Karen the contract by Friday
/executive-function-copilot:journal feeling foggy after lunch, took GLP-1 Tuesday
/executive-function-copilot:inbox
/executive-function-copilot:triage
/executive-function-copilot:briefing
```

Tab-complete from `/cap` is fine; the namespaced form is required.

## Suggested scheduled tasks (Cowork)

| Schedule | Prompt |
|---|---|
| Weekdays 7:30 AM | *"Run my morning briefing. Read my inbox, overdues, active projects, and operating manual. Produce today's anchor goal, must-do, and the first 10-minute action."* |
| Weekdays 12:30 PM | *"Midday reset. Glance at this morning's plan. What got done, what's still in play, what should be deferred? One focused next action."* |
| Weekdays 5:30 PM | *"Run my shutdown. Capture what got done, where each open loop now lives, the first task for tomorrow, and give me permission to stop."* |
| Friday 3:30 PM | *"Run my weekly review. Wins, dropped balls without shame, recurring obstacles, three outcomes for next week."* |
| Sunday 6:00 PM | *"Set up next week. Look at my calendar, current commitments, and last week's review. Stage Monday's first action."* |

## Tone and safety

The plugin's coaching tone is calibrated by Dave's operating manual (stored in `efc.operating_manual`, currently v1):

- Skip preamble. Lead with the action.
- One must-do, not three.
- Decision-ready summaries. Format cues that land: *"Here's what we're doing now / not doing now,"* *"If we do X, we slip; if we cut Y, we ship,"* *"Here's the fastest path that still meets the goal."*
- Counter scope creep aggressively.
- Honor flow when it's hot — don't break it for status updates.
- Honor the warm-up tax — a 30-min interruption can cost the day.
- Don't propose color-coded calendars or rigid time-blocking — they've been tried and didn't stick.
- Don't reinforce shame. Surface "loudest thing wins" patterns; don't punish them.
- I am not a clinician. I do not diagnose, prescribe, or treat. I _do_ surface patterns that may warrant a conversation with Dave's therapist or doctor.

## License

MIT. See [`LICENSE`](LICENSE) (or just the `license` field in `.claude-plugin/plugin.json` for now).

## Acknowledgments

David Allen's *Getting Things Done* is the source of the GTD model. The four-layer architecture and operating-manual approach are local inventions; if useful to you, take and adapt.
