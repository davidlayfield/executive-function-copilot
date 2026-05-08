# Dave OS — Session Handoff

_Last updated: 2026-05-08 08:00 ET (after a 24-hour build sprint)._

This document is for a **fresh Claude session picking up where the previous session ran out of context**. If you're that session: read this first, then `docs/ARCHITECTURE.md`, then ask Dave one clarifying question if needed and proceed.

If you are Dave: this is the doc you copy/paste at the top of a new chat to bring a fresh assistant up to speed.

---

## TL;DR — what is this project

**Dave OS** is a personal-life operating system built around an executive-function-coaching Claude Code / Cowork plugin. It captures everything Dave is doing, feeling, planning, communicating, and reading; classifies and prioritizes; coaches with morning briefings + nightly reflections; and is now autonomously processing his Gmail inbox.

It has:
- **22+ plugin commands** (capture, journal, briefing, inbox-tasks, inbox-show, inbox-update, inbox-archive, inbox-whitelist, inbox-digest, inbox-rules, inbox-unsubscribe, inbox-report, mine-leads, mine-knowledge, calendar, plus the original 10 coaching commands)
- **15 plugin skills** (executive-function-coaching, safety-and-boundaries, email-classification, ymyl-detection, email-scoring, email-task-extraction, newsletter-extraction, unsubscribe-manager, inbox-rules-engine, deep-dive-mining, plus 5 coaching skills)
- **5 sub-agents** (task-triage, routine-designer, reflection-coach, accountability, safety-boundary)
- **27 `efc.*` Postgres tables** in Supabase project `clawd-context` (`psmkklhyfkivyokhaiga`)
- **2 `openbrain.*` additions** (`email_bodies` table + `v_email_with_body` view)
- **11 autonomous routines** (8 scheduled tasks + 2 systemd timers on Ralph + 1 one-shot backfill)
- **Plugin version: 0.10.0** distributed via local marketplace + GitHub `https://github.com/davidlayfield/executive-function-copilot`

Today (2026-05-08), the system started actively triaging Dave's real Gmail. The brain has produced ~6 active email-derived tasks (Atlas timeout, BoA YMYL, Mallard Ridge DSCR, etc.) all with proper score reasons. Calendar is wired across 5 accounts with 374 events. Backfill of 154k historical emails is running on Ralph and has been since last night.

---

## The four-layer architecture

```
L4 — Coaching surface (plugin commands + skills, Cowork blue-dot delivery)
        ↑                ↓
L3 — Autonomous reflection (nightly cron, daily 2 AM Opus deep-dive, weekly summaries)
        ↑                ↓
L2 — Structured personal data (efc.* schema in Supabase)
        ↑
L1 — Firehose (OpenBrain memories — Gmail full-bodies, calls, ChatGPT/Claude, GChat, YouTube)
```

See `docs/ARCHITECTURE.md` for full diagrams and decisions.

---

## What's running autonomously right now

| # | Routine | Where | Cadence | Notify | What it does |
|---|---|---|---|---|---|
| 1 | `openbrain-gmail-ingest` | systemd on Ralph | every 1 min | — | Pulls full Gmail message bodies + threads via OAuth, writes to `openbrain.email_bodies` |
| 2 | `efc-backfill-email-bodies` | systemd one-shot on Ralph | running until done (~14h total) | — | Re-fetches all 154k historical Gmail threads with `format=full` to populate bodies (was snippet-only). Started 2026-05-07 23:59 UTC. **As of 08:00 ET 2026-05-08 ~70% done.** |
| 3 | `dave-os-calendar-ingest` | systemd on Ralph | every 10 min | — | Pulls Google Calendar events for 5 accounts via OAuth, writes to `efc.calendar_events` |
| 4 | `dave-os-inbox-process` | Cowork scheduled task | every 5 min | silent | The brain. Reads new email_bodies, classifies + YMYL + scores + extracts tasks. **Pinned to Sonnet** (was accidentally Opus until 22:46 ET last night). **90-day date cap** — older emails bulk-marked as `noise/date_cap_90d` without LLM. |
| 5 | `dave-os-deep-dive-mine` | Cowork scheduled task | daily 2 AM ET | silent | Opus deep-dive over email clusters → `efc.sales_leads` + `efc.knowledge_atoms` |
| 6 | `dave-os-morning-briefing` | Cowork scheduled task | daily 6:34 AM ET | blue dot + push | Reads operating manual + inbox + tasks + journal + calendar + yesterday's plan. Surfaces today's brief. |
| 7 | `dave-os-nightly-reflection` | Cowork scheduled task | daily 10:03 PM ET | blue dot | Composes 150-300 word reflection → `efc.daily_reflections` |
| 8 | `dave-os-weekly-newsletter-digest` | Cowork scheduled task | Mon 8:07 AM ET | blue dot | Story extraction from whitelisted newsletters → digest |
| 9 | `dave-os-weekly-unsubscribe-brief` | Cowork scheduled task | Mon 8:36 AM ET | blue dot | Auto-attempt unsubscribes from queue + surface manual ones |
| 10 | `dave-os-weekly-inbox-report` | Cowork scheduled task | Fri 4:03 PM ET | blue dot | Plain-English metrics: classifications, throughput, automation rate, top senders, recommendations |
| 11 | `dave-os-weekly-mining-summary` | Cowork scheduled task | Sun 6:01 PM ET | blue dot | Surfaces top 5 unreviewed sales leads + top 5 knowledge atoms with action prompts |

---

## What broke and got fixed during the build

Documented for reference; no current action needed unless symptoms recur.

| Issue | When | Fix |
|---|---|---|
| `/plugin` slash command not available in Dave's environment | session 1 | Use `claude plugin` CLI subcommand instead. Plugin install path: `claude plugin marketplace add /path` + `claude plugin install <name>@<marketplace>` |
| Plugin marketplace.json `source` field validation | session 1 | Use `"./"` not `"."` for self-contained plugin marketplace |
| Skills layout in plugin | session 1 | `skills/<name>/SKILL.md` (subdirectory), NOT flat `.md`. Frontmatter requires `description` field. |
| OpenBrain Gmail snippets only (avg 455 chars) | sprint day | Modified `openbrain_gmail_ingest.py` on Ralph to use `format=full` and write full bodies to `openbrain.email_bodies`. Backup at `.bak-20260507-2338`. |
| Gmail thread_id type mismatch | sprint day | `openbrain.memories.thread_id` is uuid-typed but Gmail uses 16-char hex. Linkage stays in `email_bodies.thread_id` (text) and `raw_entries.source_metadata.thread_id`. View `openbrain.v_email_with_body` abstracts this. |
| PostgREST default 1000-row cap on RPC results | backfill | Use `text[]` return type instead of `TABLE`. See `openbrain.list_missing_email_body_threads(text)`. |
| dflayfield + urbanorigin OAuth tokens were issued by desktop client but ingester read web client's `oauth_client.json` | session 5 | Renamed `oauth_client.json` → `oauth_client.web.bak.json`; copied `oauth_client_desktop.json` → `oauth_client.json` |
| **M2 routine using Opus instead of Sonnet on years-old emails (~754 wasted Opus calls)** | session 5 | v4 routine: hard 90-day date cap + explicit Sonnet pin in prompt. Step 1.5 bulk-marks all >90d emails as `rules-first:date-cap` in one cheap insert. |
| **DaveOS triage didn't archive source Gmail thread** (loop wasn't closed) | this morning | v0.10.0: `/inbox-update done|drop` now archives source thread on Ralph via `gmail_archive.py`. New `/inbox-archive <id>` for explicit archive without status change. |

---

## Critical decisions log (read before changing anything)

These are the architectural commitments. Don't undo them without explicit Dave conversation.

1. **Schema location:** `efc.*` in `clawd-context` Supabase project. NOT in `atlas.*` (that's GSH portfolio data, separate from personal life). NOT in a new project (cost + MCP wiring already there).

2. **OAuth tokens go in Supabase Vault** (`vault.secrets`) NOT AWS Secrets Manager. Vault is enabled, holds 5 secrets already. (Currently most tokens are still in `~/.clawdbot/credentials/google/` files on Ralph; migration to Vault is pending but not blocking.)

3. **Mission Control is being decommissioned slowly.** Plan: `docs/PHASE-4-INBOX-AI.md` § 15a. Don't add new MC dependencies. Email read/send/archive lives in Dave OS via direct Google APIs. Calendar same. Plaid (Phase 6) gets its own native integration. News / briefings / memory / projects already subsumed.

4. **No Telegram delivery.** Dave doesn't like it and is retiring. All notifications go via Cowork blue-dot + macOS push.

5. **No structured time-blocking suggestions.** Dave's manual rule: color-coded GCal categories, "sacred" Flow days, pre/post meeting blocks all tried and didn't stick. Don't propose another version.

6. **Cost: routines use Dave's Claude Max 20x plan quota** (he rarely above 50% utilization). Marginal cost ≈ $0 within plan limits. **DO NOT set up metered Anthropic API billing without explicit Dave approval.**

7. **M2 routine is Sonnet, not Opus.** Pinned in routine prompt. 90-day hard date cap. Anything older bulk-marked deterministically.

8. **Deep-dive mining IS Opus, by design.** Capped at 20 clusters per run. Different table outputs (sales_leads, knowledge_atoms).

9. **YMYL never gets autonomous action even at Delegator level.** Hard constraint.

10. **Capture friction = zero is the design goal.** Anything that requires Dave to change behavior dies.

11. **Subsumed Clearpath plugin.** Old plugin at `/Users/davidlayfield/Desktop/Manual Library/code_projects/clearpath-plugin/` is dormant since Feb 2026. Design lifted into Dave OS Phase 4. Don't try to revive Clearpath; build inside Dave OS.

12. **`info@apartmentsmart.com` is excluded from OpenBrain ingestion** (huge volume shared mailbox; not Dave-relevant). Special-case design TBD in a separate session.

13. **Operating manual is single source of truth for "how Dave works."** Read `efc.operating_manual WHERE is_current=true` before doing any coaching work. The "Rules for Claude when coaching me" section is non-optional.

---

## Schema reference (`efc.*`, 27 tables)

GTD core (Phase 1):
- `areas_of_focus`, `projects`, `tasks` (rich — score_dimensions jsonb, ymyl_alert jsonb, source_email_id, thread_id, etc.), `contexts`, `task_contexts`, `inbox_items`, `daily_plans`, `digests`, `weekly_reviews`, `operating_manual`, `poller_state`

Personal-data layer (Phase 1B):
- `journal_entries` (state observations w/ mood, energy, topic_tags, is_sensitive)
- `people` (relationship graph w/ importance_score, relationship_tags, response_pattern)
- `interactions` (per-exchange log; trigger auto-syncs `people.last_interaction_at`)
- `daily_reflections` (L3 nightly output)

Inbox-AI (Phase 4 M1):
- `inbox_email_log` (append-only classification log; UNIQUE on `(account, message_id)`)
- `inbox_rules`, `inbox_sessions`, `unsubscribe_queue`, `newsletter_sources`, `newsletter_interests`, `newsletter_digests`

Deep-dive mining (Phase 4.5):
- `sales_leads`, `knowledge_atoms`, `deep_dive_clusters`

Calendar (Phase 5 M1):
- `calendar_events`, `calendar_sync_state`
- Views: `v_calendar_today`, `v_calendar_this_week`, `v_calendar_busy_days`

OpenBrain additions (Phase 1.D):
- `openbrain.email_bodies` — full Gmail bodies, addresses, List-Unsubscribe
- View `openbrain.v_email_with_body` joins memories + raw_entries + email_bodies

PostgREST exposed schemas: `public, graphql_public, atlas, efc, openbrain`. Both `efc.*` and `openbrain.*` need this exposure to be accessible via Supabase REST API.

---

## OAuth scopes per account (verify before any Gmail-write work)

```
gsh           ✅ gmail.modify + gmail.send + calendar (full work account)
housr.ai      ✅ gmail.modify + gmail.send + calendar (full work account)
apartmentsmart✅ gmail.modify + gmail.send + calendar (full work account)
urbanorigin   ❌ gmail.readonly + calendar.readonly (re-auth needed for archive)
dflayfield    ❌ gmail.readonly + calendar.readonly (re-auth needed for archive)
                 NOTE: Gmail uses IMAP (app password), not OAuth — see /home/ubuntu/.clawdbot/credentials/google/dflayfield@gmail.com/imap_app_password
                 Calendar OAuth was set up via desktop client last night.
```

Token files: `~/.clawdbot/credentials/google/<email>/token.json` on Ralph.
OAuth re-auth helper: `services/calendar-ingester/oauth_authorize.py` (run on Mac, scp to Ralph).

---

## What's in flight / pending right now

In rough priority order, with everything in `efc.inbox_items` for the morning brief:

| # | What | Priority | Notes |
|---|---|---|---|
| 1 | **Verify v0.10.0 archive loop end-to-end** | High | Pick a real email-derived task, run `/inbox-update <id> done`, confirm Gmail thread leaves inbox |
| 2 | **Phase 1.C — OpenBrain `enrichment_queue` investigation** | Medium | Original morning anchor. Now de-prioritized because M2 produces real tasks anyway. Read `docs/PHASE-1C-INVESTIGATION.md`. Could also just close as "no longer needed — M2 covers it." |
| 3 | Re-auth urbanorigin + dflayfield with `gmail.modify` scope | Low | Same OAuth helper, just expanded scope. Unblocks archive on those accounts. |
| 4 | Wire autonomous archive in M2 routine (rules-fired auto_archive) | Medium | Currently rules log + suggest, don't act. Gated to Drafter/Delegator autonomy. |
| 5 | M2 v4 verification — confirm 0 Opus calls and date-cap working | High | Query `efc.inbox_email_log WHERE classified_at > now() - interval '12 hours'` after morning runs |
| 6 | Backfill completion (~70% done as of 08:00 ET 5/8) | Passive | Will finish on its own by mid-day Friday |
| 7 | OAuth token migration → Supabase Vault | Low | Currently file-based on Ralph; should move to vault.secrets eventually |
| 8 | **Phase 6 — Plaid finance** | Medium | Separate session per Dave's earlier decision |
| 9 | Phase 5 M2 — Calendar WRITE (accept/decline/create) | Low | Read-only is sufficient for now |
| 10 | `info@apartmentsmart.com` triage design (no OpenBrain ingest) | Low | Separate session |
| 11 | IMAP path for dflayfield Gmail bodies | Low | OAuth path covers 4 accounts; IMAP archive needs different approach |
| 12 | Telegram capture surface | Cancelled | Dave retiring Telegram. Cowork mobile + Dispatch covers mobile capture. |

---

## Verification queries — run these to assess system health

```sql
-- Phase 4 M2 health
SELECT classified_by_model, count(*)
FROM efc.inbox_email_log
WHERE classified_at > now() - interval '24 hours'
GROUP BY 1 ORDER BY 2 DESC;
-- Expected after v4 fix: lots of 'rules-first:*' + some 'claude-sonnet-4-5'
-- Bug signal: any 'opus' or 'claude-opus-*' = v4 not deploying or session-default-model issue

-- Backfill progress
SELECT account, count(*) AS bodies FROM openbrain.email_bodies GROUP BY 1 ORDER BY 1;

-- Active tasks the brain has produced
SELECT count(*) FILTER (WHERE source_email_id IS NOT NULL) AS from_email,
       count(*) FILTER (WHERE ymyl_classification IS NOT NULL) AS ymyl,
       count(*) FROM efc.tasks WHERE status IN ('todo','doing','waiting');

-- Calendar accounts and event counts
SELECT account, count(*) AS events FROM efc.calendar_events GROUP BY 1 ORDER BY 1;

-- Routine health (last poll per source)
SELECT * FROM efc.poller_state ORDER BY last_polled_at DESC NULLS LAST;

-- Operating manual current
SELECT version, length(content) AS chars, is_current FROM efc.operating_manual ORDER BY version DESC LIMIT 3;

-- Today's plan (was the morning brief produced?)
SELECT * FROM efc.daily_plans WHERE plan_date = CURRENT_DATE;
```

---

## Common operations

```bash
# Connect to Ralph
ssh -i ~/.ssh/LightsailDefaultKey-us-east-1.pem ubuntu@100.73.64.27

# Trigger a calendar sync manually
ssh ralph 'sudo systemctl start dave-os-calendar-ingest.service; tail -20 /home/ubuntu/openbrain/logs/calendar-ingest.log'

# Trigger Gmail ingester manually
ssh ralph 'sudo systemctl start openbrain-gmail-ingest.service; tail -20 /home/ubuntu/openbrain/logs/gmail-hourly.log'

# Watch backfill progress
ssh ralph 'tail -20 /home/ubuntu/openbrain/logs/backfill-email-bodies.log'

# Re-run calendar full sync (skip incremental)
ssh ralph 'python3 /home/ubuntu/openbrain/connectors/gmail/openbrain_calendar_ingest.py --full'

# Manually archive a Gmail thread (used by /inbox-update done)
ssh ralph "python3 /home/ubuntu/openbrain/connectors/gmail/gmail_archive.py '<account>' '<thread_id>' --read"

# Force the M2 brain to fire now (don't wait for next 5-min boundary)
# In Cowork: open the dave-os-inbox-process scheduled task and click "Run now"

# Update the plugin after editing
cd /Users/davidlayfield/executive-function-copilot
# Edit, then bump version in .claude-plugin/plugin.json
git add -A && git commit -m "..." && git push
claude plugin marketplace update executive-function-copilot
claude plugin update executive-function-copilot@executive-function-copilot
# Then Cmd+Q the Cowork desktop app and relaunch
```

---

## Files of record (in this repo)

```
/                                        — Dave OS plugin root
├── .claude-plugin/
│   ├── plugin.json                      — version 0.10.0
│   └── marketplace.json
├── README.md                            — install + use, current
├── CHANGELOG.md                         — every version since 0.1.0
├── docs/
│   ├── ARCHITECTURE.md                  — full system design + decisions log
│   ├── PHASE-1C-INVESTIGATION.md        — OpenBrain enrichment_queue diagnostic playbook
│   ├── PHASE-4-INBOX-AI.md              — Clearpath subsumption synthesis (~600 lines)
│   └── HANDOFF.md                       — THIS FILE
├── commands/                            — 22+ plugin commands
├── skills/                              — 15 plugin skills (each in its own dir w/ SKILL.md)
├── agents/                              — 5 sub-agents
├── examples/                            — 4 sample outputs
└── services/
    ├── openbrain-poller/                — Phase 1.C poller (deferred, see todo)
    │   ├── REFERENCE-openbrain-gmail-ingester.py    — snapshot of live Ralph code
    │   ├── REFERENCE-gmail-archive.py               — snapshot of Ralph helper
    │   └── REFERENCE-dave-os-inbox-process.md       — snapshot of M2 routine prompt
    └── calendar-ingester/
        ├── openbrain_calendar_ingest.py             — snapshot of live Ralph code
        ├── dave-os-calendar-ingest.{service,timer}  — systemd units
        ├── install-on-ralph.sh                      — one-shot deploy
        └── oauth_authorize.py                       — OAuth desktop-flow helper (run on Mac)
```

---

## Files of record (NOT in this repo — on Ralph)

These are deployed and live; the repo has reference snapshots only.

```
/home/ubuntu/openbrain/connectors/gmail/
├── openbrain_gmail_ingest.py                — Gmail ingester (live, every 1 min)
├── openbrain_calendar_ingest.py             — Calendar ingester (live, every 10 min)
├── backfill_email_bodies.py                 — One-shot historical backfill (running)
└── gmail_archive.py                         — Archive helper (called by /inbox-update)

/etc/systemd/system/
├── openbrain-gmail-ingest.{service,timer}        — every 1 min
├── dave-os-calendar-ingest.{service,timer}       — every 10 min
└── efc-backfill-email-bodies.service             — one-shot (currently running)

/etc/efc/env                                — SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (mode 600)
/home/ubuntu/.clawdbot/credentials/google/<email>/  — OAuth tokens per account
/home/ubuntu/openbrain/logs/                — All ingester logs
```

---

## Personal context the assistant should know

- **Dave Layfield** — co-founder of HousrAI (Vitals, Atlas products), executive at Green Street Housing (affordable housing dev/ops in MD).
- **Operating manual at `efc.operating_manual is_current=true`** — read this before any coaching. Key points: skip preamble, 1 must-do not 3, decision-ready summaries, counter scope creep, no rigid time-blocking, honor flow, surface "loudest thing wins" without shame.
- **Dave is on Claude Max 20x plan**, almost never above 50% utilization. Routines draw from same quota. Marginal cost ≈ $0 within plan limits.
- **Time context** is injected via `~/.claude/hooks/time-context.sh` UserPromptSubmit hook. Honor the window labels (peak / crash / family-evening / late-evening fake-energy zone).
- **Dave has cataracts** — high-contrast text, large font preferences. Tables and bullets > walls of text.
- **OpenBrain** is Dave's existing personal AI memory system (~31k+ memories). Search aggressively before asking him questions.

---

## What to do first in a fresh session

1. **Read this file** end-to-end.
2. **Read `docs/ARCHITECTURE.md`** for the system design.
3. **Run the verification queries** above to confirm system state.
4. **Check `efc.inbox_items WHERE status='pending'`** — that's what's queued for triage.
5. **Check `efc.tasks WHERE status IN ('todo','doing','waiting') ORDER BY priority_score DESC`** — that's what the brain has surfaced.
6. **Ask Dave one question:** "I've read the handoff — picking up from [last item from the in-flight list]. Sound right?"
7. Don't propose architectural changes without reading the decisions log above.
8. Don't redo work that's already done — verify with SQL before building.

---

## Sister documents

- `docs/ARCHITECTURE.md` — system design, schema, decisions log, phase plan
- `docs/PHASE-1C-INVESTIGATION.md` — OpenBrain extraction diagnostic playbook
- `docs/PHASE-4-INBOX-AI.md` — Clearpath subsumption + Phase 4 milestones
- `CHANGELOG.md` — version history
- `README.md` — install + use

GitHub: https://github.com/davidlayfield/executive-function-copilot
Repo HEAD when this was written: `e1f3bd1` (v0.10.0)
