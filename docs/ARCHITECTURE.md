# Architecture — Executive Function Copilot / Dave OS

_Last updated: 2026-05-07 (v0.3.0)_

This document describes what EFC actually is, how the layers fit together, and what's shipped vs planned. It supersedes the README's original framing of "a markdown plugin with coaching prompts" — that was the v0.1 design.

## What this is, in one paragraph

EFC is a **personal data system with a coaching surface on top.** It captures Dave's actions, thoughts, observations, and interactions across every digital and physical context, organizes them into a GTD-faithful structured layer in Supabase, and uses that data to coach him on what to do today, what's drifting, and what patterns are showing up over weeks and years. The medical-device disclaimer remains: it does not diagnose, prescribe, or treat — but it is allowed to surface patterns that prompt conversations with Dave's actual therapist or doctor (per his operating manual).

It's also called **Dave OS** when speaking aspirationally, because the long-term scope is "everything Dave is doing, feeling, and tracking" — not just task management.

## The four-layer architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│ L4 — Coaching surface                                                    │
│  /briefing  /capture  /journal  /triage  /shutdown  /weekly-review       │
│  /unstuck   /reframe  /design-routine  /plan-project  ...                │
│  (15 plugin commands + 9 skills + 5 sub-agents — all markdown,           │
│   loaded by Claude Code & Cowork at session start.)                      │
└─────────────────────────────────────────────────────────────────────────┘
                              ↑                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ L3 — Autonomous reflection                                              │
│  Nightly cron on Ralph: read today's L2, compare across time, write      │
│  a row to efc.daily_reflections. Cross-temporal pattern detection,       │
│  morning-brief drafting. (Not yet built.)                                │
└─────────────────────────────────────────────────────────────────────────┘
                              ↑                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ L2 — Structured personal data — Supabase schema `efc.*`                  │
│  GTD core:                  Personal data:                               │
│   areas_of_focus             journal_entries  ← state observations       │
│   projects                   people           ← relationship graph       │
│   tasks                      interactions     ← per-exchange log         │
│   contexts                   daily_reflections← L3 output                 │
│   task_contexts              operating_manual ← versioned, current=true   │
│   inbox_items                                                            │
│   daily_plans / digests / weekly_reviews                                 │
│   poller_state               (15 tables, RLS on, single-user.)           │
└─────────────────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────────────────┐
│ L1 — Firehose — OpenBrain (`openbrain.memories`, ~188k rows and growing) │
│  Sources: Gmail, Fireflies calls, ChatGPT/Claude history, GChat,         │
│  YouTube, Mission Control briefings, AI sessions.                        │
│  Bridge: openbrain-poller (systemd on Ralph, every 5 min) reads new      │
│  memories, forwards Dave-owned action_items into efc.inbox_items.        │
│  Status: pipeline deployed; OpenBrain's own action_items extraction is   │
│  sparse (2 of 188k populated) — currently the unblocker.                 │
└─────────────────────────────────────────────────────────────────────────┘
```

**Read top-to-bottom** for "how a thought becomes a coaching response." A capture in chat (L4) writes to `inbox_items` (L2). The nightly job (L3) reads L2 and writes a reflection row. Tomorrow's `/briefing` (L4) reads the reflection plus pending L2 state and surfaces the day's plan.

**Read bottom-to-top** for "how external events become coaching." A Fireflies call (L1) becomes an OpenBrain memory. The poller bridges it to `inbox_items` (L2) if it contains Dave-owned actions. `/triage` routes it to a task or a journal entry. The nightly job notices patterns. Tomorrow's brief raises them.

## Why these four layers (and not, say, "just put everything in OpenBrain")

| Layer | What it's good for | What it's bad at |
|---|---|---|
| **L1 OpenBrain** | Firehose ingestion. Vector + keyword search across heterogeneous sources. Conversational memory recall. | Structured queries with status, due dates, project relationships. Joins. State machines. |
| **L2 EFC** | GTD-faithful relational model. Status / priority / contexts / hierarchy. Cross-temporal queries. Predictable schema for downstream jobs. | Conversational recall. Open-ended free-text search across years of chats. |
| **L3 Reflection** | Periodic synthesis. Pattern detection across time. Cross-temporal comparisons ("vs. same Thursday a year ago"). | Real-time response. |
| **L4 Coaching** | Real-time decision-ready summaries. Honors the operating manual. Adaptive to time-of-day window. | Memory of what Dave said two weeks ago (that's L1's job). |

EFC and OpenBrain are complementary, not competing. The poller is the bridge.

## Schemas

### `efc.*` — 15 tables (v0.3.0)

| Table | Purpose | Key fields |
|---|---|---|
| `areas_of_focus` | Top-level life buckets (HousrAI, GSH, Family, Home, Health, etc.) | name, status |
| `projects` | Outcome-shaped commitments. Areas → Projects. | area_id, desired_outcome, status, weight (0-5) |
| `tasks` | Verb-first physical actions. 1 level of subtasks via `parent_task_id`. | project_id, status, priority, energy_required, due_date, deferred_until, openbrain_memory_id, external_source |
| `contexts` | Orthogonal GTD tags. 13 system-seeded (`@home`, `@flow`, `@phone`, `@errand`, …). | name, is_system |
| `task_contexts` | M2M between tasks and contexts. | task_id, context_id |
| `inbox_items` | Captured-but-not-yet-triaged. Source: manual, openbrain, github, email, dispatch. | raw_text, source, openbrain_memory_id, status, triaged_to_task_id |
| `journal_entries` | State observations: mood, body, food, medication, energy, relationships. **Not** action items. | entry_text, mood, energy, topic_tags, is_sensitive, inbox_item_id |
| `people` | Relationship graph. | name, relationship_type, role, strengths, delegation_areas, last_interaction_at, cadence_target_days |
| `interactions` | Per-exchange log. Trigger auto-syncs `people.last_interaction_at`. | person_id, channel, direction, sentiment, summary, openbrain_memory_id |
| `daily_plans` | Persistent record of each day's plan. | plan_date (unique), anchor_goal, must_/should_/could_task_ids, ten_min_action |
| `daily_reflections` | L3 output: nightly autonomous summary. | reflection_date (unique), summary, mood_arc, patterns_noted, comparisons (jsonb) |
| `digests` | Daily digest log: overdues + Dave's keep/push/drop/done decisions. | digest_date (unique), decisions (jsonb) |
| `weekly_reviews` | Friday/Sunday review records. | week_starting (unique), wins, dropped_balls, top_outcomes_next_week |
| `operating_manual` | Versioned manual. Exactly one `is_current=true` row at any time (partial unique index enforces). | version, content, is_current |
| `poller_state` | Per-source last_polled_at + status + notes. | source (PK), last_polled_at, last_run_status |

### Supabase project

- **Project:** `clawd-context` (`psmkklhyfkivyokhaiga`)
- **Schemas exposed to PostgREST:** `public, graphql_public, atlas, efc, openbrain`
- **Roles:** `service_role` (poller, server-side jobs), `authenticated` (Cowork plugin via supabase MCP); RLS permissive — single-user.
- **Migrations:** applied via Supabase MCP `apply_migration` tool. See migration history with `list_migrations`.

## Time-context awareness

Every Claude Code / Cowork prompt fires `~/.claude/hooks/time-context.sh` (registered as a `UserPromptSubmit` hook) which prepends:

```
<time-context>
Now: 2026-05-07 15:44 Thursday EDT
Window: post-crash — distractions usually winning, low real focus
</time-context>
```

The window labels come from Dave's operating manual — peak (07:00–11:30), crash (13:00–14:00), post-crash, family/evening, and late-evening "fake-energy zone." Coaching responses are expected to honor the window: smaller plans during crash, no heavy-cognitive-load proposals after 13:00, and a flag when something is being attempted in the late-evening zone.

## Directory layout

```
executive-function-copilot/
├── .claude-plugin/
│   ├── plugin.json              # version, name, author
│   └── marketplace.json         # local-marketplace wrapper
├── .mcp.json                    # ships empty — plugin makes no MCP assumptions
├── README.md                    # install + use, cross-surface
├── CHANGELOG.md                 # version history
├── docs/
│   └── ARCHITECTURE.md          # this file
├── skills/                      # 9 skills, each as SKILL.md
│   ├── executive-function-coaching/SKILL.md
│   ├── safety-and-boundaries/SKILL.md
│   └── ...
├── commands/                    # 15 commands (markdown with frontmatter)
│   ├── capture.md               # GTD capture — writes to efc.inbox_items
│   ├── journal.md               # state observations — writes to efc.journal_entries
│   ├── inbox.md                 # show pending captures
│   ├── triage.md                # do/defer/delegate/drop/journal each item
│   ├── briefing.md              # morning brief reading L2 + manual + time
│   ├── daily-plan.md            # legacy conversational planner
│   ├── shutdown.md              # end-of-day ritual + writes shutdown_notes
│   ├── weekly-review.md         # writes to efc.weekly_reviews
│   └── ...
├── agents/                      # 5 sub-agents
│   ├── task-triage-agent.md
│   ├── routine-designer-agent.md
│   ├── reflection-coach-agent.md
│   ├── accountability-agent.md
│   └── safety-boundary-agent.md
├── examples/                    # 4 sample outputs
└── services/
    └── openbrain-poller/        # systemd service for Ralph
        ├── poller.py            # ~150 lines, idempotent
        ├── requirements.txt
        ├── efc-poller.service   # systemd oneshot
        ├── efc-poller.timer     # every 5 minutes
        ├── deploy-to-ralph.sh   # one-shot install
        └── README.md
```

## Phase plan

### ✅ Phase 1.A — L2 GTD core (shipped 2026-05-07)
- 11 core tables, RLS, contexts seeded.
- Operating manual migrated from local markdown to versioned `efc.operating_manual` row.
- Plugin commands wired to Supabase via the `supabase` MCP: `/capture`, `/inbox`, `/triage`, `/briefing`.

### ✅ Phase 1.B — L2 personal-data layer (shipped 2026-05-07, v0.3.0)
- 4 additional tables: `journal_entries`, `people`, `interactions`, `daily_reflections`.
- `/journal` command. `/triage` extended to route observations.
- Trigger keeps `people.last_interaction_at` in sync.

### 🚧 Phase 1.C — OpenBrain bridge (deployed but not extracting)
- Poller deployed on Ralph with venv, env, and systemd unit.
- Pipeline confirmed end-to-end: connects, queries, writes successfully.
- **Blocker:** OpenBrain's own `action_items` extraction is sparse (2 of 188k memories populated). Investigation tomorrow:
  - Read `openbrain.enrichment_queue` and `openbrain.ingest_runs` to find why extraction stopped.
  - Either fix OpenBrain extraction (preferred — benefits OpenBrain too) or add a fallback Anthropic-API extractor inside the poller.
  - Add `extraction_model` column to `efc.inbox_items` for quality monitoring (precision = items_kept / items_extracted, grouped by model).

### 🔜 Phase 2 — L3 autonomous reflection
- Nightly cron on Ralph reading L2.
- First version: summary, mood_arc, people_touched.
- Cross-temporal comparisons (vs. last week, last month, year-ago) iterate from there.

### 🔜 Phase 3 — Capture surfaces
- Telegram bot for mobile capture (Mission Control already has the bot wired).
- Voice capture via Cowork mobile.
- Email-to-inbox via Mission Control's existing Gmail connection.

### Later
- Delegation engine (uses `efc.people.delegation_areas` to suggest hand-offs proactively).
- Pattern analytics dashboard (private, local).
- Habit / routine adherence tracking.

## Decisions made today (2026-05-07)

These are decisions you'd otherwise have to re-derive every session. Logged here so they're durable.

| Decision | What was chosen | Why |
|---|---|---|
| **Schema location** | `efc.*` in `clawd-context` — same project as OpenBrain. Stays out of `atlas.*` (Atlas concerns ≠ personal life). | Cheapest, fastest, MCP wired everywhere. Personal-data project already exists. |
| **Storage philosophy** | Structured GTD layer in EFC; OpenBrain stays the firehose. Cross-references both ways. | Each does what it's good at. See "Why these four layers." |
| **Extraction approach** | Fix OpenBrain's own extraction first; fall back to a small Anthropic model inside the poller only if OpenBrain extraction can't be revived. | OpenBrain extraction benefits everything else, not just EFC. Fixing once > working around. |
| **Quality monitoring** | `extraction_model` column on `inbox_items`; weekly precision rollup; if Haiku precision < 70% for two weeks, escalate to Sonnet. | Cheap metric, real signal. |
| **Capture friction tolerance** | Inbox can backlog. Nudge once at >20 pending. No pile-on reminders. | GTD-faithful but tolerant. Strict-zero-inbox has historically caused systems to fall off. |
| **Hierarchy depth** | Areas → Projects → Tasks + 1 level of subtasks. No deeper. | Faithful GTD; prevents over-nesting. |
| **GitHub auto-import scope** | Issues assigned to `davidlayfield` in `housr-ai/*` org. Personal repos opt-in. | Default-on for work; opt-in for personal so the inbox doesn't get polluted. |
| **Privacy / encryption** | Plain Postgres + RLS. Single-user. Sensitive entries flagged via `journal_entries.is_sensitive`. | Don't over-engineer. RLS + Supabase encryption-at-rest is sufficient for this user. |
| **Operating manual storage** | DB row is source of truth (`efc.operating_manual`). Local file is a fast cache. Sync on edit. | Cross-surface (CLI, Cowork web, mobile via Dispatch). |
| **What "I'm not a clinician" means** | I do not diagnose, prescribe, or treat. I _am_ a high-level coach for organization, GTD, and executive function. **And:** I surface patterns that may warrant a conversation with Dave's actual therapist or doctor. Frame as "worth asking about," never "you should take X." | Updated in Dave's operating manual at his explicit direction. Pattern recognition that prompts professional conversations is part of the job. |
| **Failed experiments — do not propose again** | Color-coded GCal categories, sacred Flow-day systems, pre/post meeting blocks, Tue/Thu Family Admin sprints, Pomodoro variants, weekly time-grids. | All tried. None stuck. Documented in the operating manual. The system designs around their absence, not toward another version. |

## How this stays alive (the 90-day test)

The system fails if Dave falls off using it. Three guardrails:

1. **Capture must be near-zero friction across surfaces.** Telegram and voice are coming so the inbox can be hit from anywhere within 5 seconds of a thought.
2. **One stickiness anchor.** The morning `/briefing` is the bet. If Dave runs it on >80% of days for 30 days, the system is alive.
3. **The system uses itself.** The build TODO is captured as inbox items. The Chipotle observation is in `journal_entries`. Every working session adds rows. There is no "real data starts later."

If briefing-run rate drops below 50% across two consecutive weeks, **redesign — don't push.** The system surviving is more important than its current shape.
