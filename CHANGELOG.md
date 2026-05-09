# Changelog

All notable changes to this project go here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## 0.11.0 — 2026-05-08 (Phase 4 M3 — waiting-task follow-up resurfacer)

Closes the second loop in inbox triage. Before this, `/inbox-update <id> waiting Tom` would silently park a task forever — Tom's reply showed up in Gmail but the task stayed in `waiting` until Dave manually noticed. After this, the M2 brain detects replies on watched threads and surfaces chases for stale waits.

### Schema (migration `efc_tasks_waiting_resurface_columns`)
- `efc.tasks` adds 6 columns: `replied_at`, `reply_summary`, `reply_message_id`, `chase_nudged_at`, `chased_at`, `waiting_since`.
- 2 partial indexes for cheap lookups (waiting tasks by `thread_id`; waiting tasks by `waiting_since`).
- New view `efc.v_tasks_waiting_followups` — what the morning brief reads to surface follow-ups.
- Backfill: any task already in `waiting` status gets `waiting_since = COALESCE(updated_at, created_at)`.

### Reply detection (Q1=A: thread-match, Q2=C: Sonnet-summarized)
- M2 routine adds Step 8.5: for each new email in batch, check whether `thread_id` matches a `status='waiting'` task. If yes, run a one-shot Sonnet summary and flip the task to `todo` with title prefix `[REPLY] <person>: <what they said> — <next action>`.
- Self-reply guard: emails from Dave's own addresses do not flip waiting tasks.
- Idempotency: `replied_at IS NULL` and `[REPLY]` title prefix prevent double-flips when multiple replies arrive on the same thread.

### Chase routine (Q3=C: tiered 3d soft / 7d hard)
- New scheduled task `dave-os-waiting-chase` — daily 6:03 AM ET, just before morning briefing.
- Day-3 soft nudge: sets `chase_nudged_at`, no status change. Surfaced in tomorrow's brief as "still waiting".
- Day-7 hard chase: flips status back to `todo`, prefixes title `[CHASE — Nd no reply]`, sets `chased_at`. Forces Dave to decide: chase / drop / extend.
- Defensive: skips tasks updated in the last 24 hours (don't fight a recent manual action) and tasks with `waiting_on_person IS NULL`.

### Plugin
- New command `/inbox-waiting [list|stale|nudged|chased]` — view all tasks in `waiting` status, sorted oldest first, with chase state visible.
- `/inbox-update` updated: any flip OUT of `waiting` clears the chase state; any flip INTO `waiting` sets `waiting_since = now()` and resets chase fields. Title cleanup strips `[CHASE — Nd no reply]` prefix when Dave acts on a chased task.

### Morning brief
- New `📬 FOLLOW-UPS` section: replies received overnight, chases that fired today, soft nudges in flight. Replies sort first because they're the highest-leverage signal — ball is back in Dave's court.

### Snapshots in repo
- `services/openbrain-poller/REFERENCE-dave-os-waiting-chase.md` (new)
- `services/openbrain-poller/REFERENCE-dave-os-inbox-process.md` (updated)
- `services/openbrain-poller/REFERENCE-dave-os-morning-briefing.md` (new snapshot)

## Unreleased — 2026-05-07 (Phase 4 M2 v2 — rules-first + Max-plan-aware)

### Changed
- **`dave-os-inbox-process` routine rewritten (v2).** Three-stage pipeline: rules-first deterministic pre-filter (~60% of emails handled free), batched LLM reasoning for the rest (Sonnet/Opus on Dave's Claude Max 20x plan = $0 marginal), batched SQL writes.
- **Batch size 30 → 100.** Max plan rarely above 50% utilization; routines should be generous, not stingy.
- **Cost model corrected.** Routine compute draws from Dave's Max plan quota, not metered API. Marginal cost ≈ $0 within plan limits. Earlier $300-3,400 estimate assumed metered API and was wrong for this user.
- Snapshot of new routine prompt: `services/openbrain-poller/REFERENCE-dave-os-inbox-process.md`.

### Rules-first heuristics (no LLM)
- Newsletter whitelist match → NEWSLETTER
- LinkedIn / Twitter / Facebook / Instagram / X / Threads / TikTok / no-reply / notification senders → NOISE (with safety check for urgency keywords in subject)
- List-Unsubscribe header + not on whitelist → log to `efc.newsletter_sources` as unreviewed (still LLM-classify the email itself)
- Display-name vs domain mismatch + credential-fishing keywords → SPAM
- Subject starts with "FYI:" / "Heads up:" / "For your records" → INFORMATIONAL
- info@apartmentsmart.com → skip (defensive, OB excludes it already)
- Emails older than 12 months get a context_richness penalty (less likely actionable now)

### Quota awareness
- 429 / rate-limit → log throttled, exit clean, next 5-min fire retries
- No batch-size shrinking; let Max quota cover bigger batches naturally

## Unreleased — 2026-05-07 (Phase 4 M2 orchestrator + brain skills shipped)

### Live (silent background)
- **Scheduled task `dave-os-inbox-process`** — Phase 4 M2 inbox-AI orchestrator. Fires every 5 minutes. Pulls new emails from `openbrain.email_bodies` not yet in `efc.inbox_email_log`, runs each through one Haiku-class LLM call returning structured JSON (classification + YMYL + score dimensions + task extraction), applies post-composite scoring rules (YMYL floors, CC ceiling, newsletter ceiling) in SQL, deduplicates against `efc.tasks`, writes everything. Silent — no notifications; morning brief surfaces results. Cost ~$0.0001/email, ~$0.86/day at full firehose.
- Skipped accounts: `info@apartmentsmart.com` (already excluded at OB ingestion).
- BATCH_SIZE=30 per run; idempotent via `(account, message_id)` unique index on `inbox_email_log`.

### How M2 + the brain compose
The four skills (`email-classification`, `ymyl-detection`, `email-scoring`, `email-task-extraction`) are the rules. The orchestrator routine is the orchestration. Each cycle:

```
new emails (openbrain.v_email_with_body)
  → classify (5+1 categories, decision tree)
  → if YMYL: extract structured alert
  → score (6 dimensions + 7 special rules)
  → if ACTIONABLE/YMYL: extract verb-first task (3-check dedup)
  → write efc.inbox_email_log (classification log)
  → write/update efc.tasks (if extracted)
  → upsert efc.people (sender contact-learning)
  → update efc.poller_state ('inbox-process')
```

### Open considerations (to revisit)
- Backlog: ~111k emails will land in `email_bodies` overnight. M2 processes 30/run × 288 runs/day = 8,640/day. Backfill of classifications will take ~13 days unless we bump batch size.
- Skill auto-loading in routine sessions: assumed plugin skills are accessible in scheduled task contexts; first runs will reveal whether classifications are sensible. If garbage, inline the skill content into the routine prompt.

## Unreleased — 2026-05-07 (last push of the night — Phase 1.D backfill running)

### Live on Ralph (background, ~14h)
- **systemd service `efc-backfill-email-bodies.service`** — one-shot Python backfill walking historical Gmail threads to populate `openbrain.email_bodies` for the 111k+ that were ingested before Phase 1.D part 2.
- **Started:** 2026-05-07 23:59:08 UTC. **Expected completion:** ~14:00 UTC Friday May 8 (overnight).
- Throttled to ~2.1 threads/sec (real measured rate; gated by Gmail API latency, not our throttle).
- Reuses live ingester's `GoogleAuth`, `get_thread`, `write_email_body` helpers. Idempotent (upserts on `(account, message_id)`); resumable (`list_missing_email_body_threads()` re-evaluates each run).
- Accounts (in order): gsh (54,754), personal (31,437), as (24,375), ai (562), urbanorigin (already done in smoke test, 0).
- Logs to `/home/ubuntu/openbrain/logs/backfill-email-bodies.log` AND `journalctl -u efc-backfill-email-bodies`.

### Schema additions
- **`openbrain.list_missing_email_body_threads(text)`** — RPC function returning thread_ids missing from `email_bodies` for a given account. Coalesces `thread_id` and `gmail_thread_id` (historical raw_entries used the latter; ingester switched to the former). Returns `text[]` (not TABLE) to bypass PostgREST's default 1000-row cap that bit us during the first attempt.

### Snapshots in repo
- `services/openbrain-poller/backfill_email_bodies.py` — backfill script (deployed copy on Ralph).
- `services/openbrain-poller/efc-backfill-email-bodies.service` — systemd unit (deployed copy on Ralph).

### Storage projection (decision logged)
- Current DB: 5.5 GB. Projected after backfill: ~11 GB. Supabase Pro tier overage cost: **~$0.40/month** ($5/year).
- Mission Control retirement frees ~800 MB (`public.mc_emails*`) — net storage delta after MC retirement is roughly the same as today.
- Decision: do the backfill. Cost trivial; value enormous (Phase 4 classification can read every historical thread).

## Unreleased — 2026-05-07 (late evening — Phase 1.D part 2 SHIPPED)

### Changed (live on Ralph)
- **`/home/ubuntu/openbrain/connectors/gmail/openbrain_gmail_ingest.py`** modified:
  - `get_thread()` now uses `format=full` instead of `format=metadata` — fetches full MIME payload alongside existing metadata.
  - New helpers: `_decode_part`, `_walk_payload`, `_extract_bodies` (MIME tree walker), `_parse_address`, `_extract_address_list`, `write_email_body` (best-effort PostgREST upsert to `openbrain.email_bodies`).
  - Thread-processing loop now calls `write_email_body(email, msg)` for each message after `ingest_memory` succeeds. Failures are logged and ignored — bodies are an enrichment, not a hard dependency.
- Original backed up at `openbrain_gmail_ingest.py.bak-20260507-2338` on Ralph.
- Snapshot of deployed version checked into this repo as `services/openbrain-poller/REFERENCE-openbrain-gmail-ingester.py` (reference only — not live).

### Verified
- Manual run on `dave@greenstreethousing.com --since 2026-05-07` produced **50 email_bodies rows across 25 threads**.
- **Avg body size: 37,079 bytes** (vs. ~455 in old snippet form — 80× more content).
- Max body 293,928 bytes (a citybizlist real-estate newsletter, HTML-only).
- 13 captured `List-Unsubscribe` headers — Phase 4 unsubscribe pipeline now has real data to work with.
- 11 emails with attachment metadata captured.
- Existing memory ingest unchanged (still working on the same threads in parallel).

### Known limitations
- **IMAP code path** (used by `dflayfield@gmail.com`) doesn't yet write to `email_bodies`. Other 4 OAuth/Gmail-API accounts are covered. Lower-priority fix.
- **HTML-only newsletters** populate `body_html` and leave `body_plain` null. Classifier will need to handle both columns (already true in any reasonable parser).
- **No backfill yet** of the existing 154k+ gmail memories. The new code only catches memories ingested going forward. A one-shot batch script can be run later to backfill.

## Unreleased — 2026-05-07 (late evening — L3 + Phase 1.D part 1)

### Added
- **Scheduled task `dave-os-nightly-reflection`** — daily 10 PM ET autonomous reflection. Reads today's tasks, journal entries, inbox activity, daily plan, interactions, yesterday's reflection. Composes a 150-300 word reflection. Saves to `efc.daily_reflections` (idempotent ON CONFLICT). Notifies via blue dot. Closes the L3 loop with the morning briefing routine.
- **Migration `openbrain_email_bodies_table`** — Phase 1.D part 1. New `openbrain.email_bodies` table for full email bodies (separate from `memories` so embeddings stay small and existing consumers unaffected). Carries body_plain, body_html, all addresses (to/cc/bcc), date_received, attachment_summary, and `list_unsubscribe`/`list_unsubscribe_post` headers (Phase 4 unsubscribe). Unique on `(account, message_id)`. RLS enabled.
- **View `openbrain.v_email_with_body`** — joins `memories` + `raw_entries` + `email_bodies` for one-shot Phase 4 reads. 154,390 gmail memories ready to be joined; 0 with body yet (ingester change in Phase 1.D part 2 will populate).

### Why two parts for Phase 1.D
- Tonight: schema additions only — additive, low risk, can't break the live ingester.
- Later: actual ingester code change (fetch `format=full`, MIME-decode, write to `email_bodies`) — needs careful test on the live every-1-min Ralph service. Better fit for a peak window.

### Schema discovery
- `openbrain.memories.thread_id` is `uuid`-typed; Gmail thread_ids are 16-char hex (not valid uuids). They can't go there. Email-thread linkage stays in `email_bodies.thread_id` (text) and `raw_entries.source_metadata.thread_id`. The view abstracts this.



### Added
- **Migration `efc_phase4_m1_inbox_ai_schema`** — 7 new tables for Phase 4: `inbox_email_log`, `inbox_rules`, `inbox_sessions`, `newsletter_sources`, `newsletter_interests`, `newsletter_digests`, `unsubscribe_queue`. All RLS-enabled. Seeded with 6 newsletter sources (AI Secret, Robotics Herald, Bay Area Letters, TechCrunch, Axios Morning, Axios AI) and 10 interest topics.
- **`efc.tasks` extended** with email-derived columns: `source_email_id`, `source_account`, `sender_name`, `sender_email`, `thread_id`, `priority_score numeric(4,3)`, `score_dimensions jsonb`, `score_reason`, `draft jsonb`, `ymyl_classification`, `ymyl_alert jsonb`. Indexes on source_email, thread, priority.
- **`efc.people` extended** with contact-learning columns: `email_normalized` (unique), `importance_score`, `relationship_tags`, `response_pattern`, `interaction_count`, `accounts_seen_on`, `organization`. Importance index for ranking.

### Decided (logged in `docs/PHASE-4-INBOX-AI.md` § 15)
All 9 Phase 4 open questions resolved:
- **Q1 Auto-send:** copy-paste only first; graduate to auto-send for low-stakes after 30 days; YMYL stays manual forever.
- **Q2 Active accounts:** 5 firehose accounts (gsh, ai, dflayfield, as, urbanorigin); `info@apartmentsmart.com` deliberately excluded — separate-session design.
- **Q3 Mission Control retirement:** MC being decommissioned slowly. OAuth tokens go in **Supabase Vault** (`vault.secrets`, confirmed enabled). Direct Google API integration in the plugin.
- **Q4 Full bodies + threads:** modify OB ingester (Phase 1.D) for both.
- **Q5 Cadence:** every 5 minutes, silent background; only morning brief notifies.
- **Q6 Newsletters:** the 6 confirmed; commands needed.
- **Q7 YMYL ceiling:** defaults fine; revisit after first weekly report.
- **Q8 Calendar:** Phase 5, own session.
- **Q9 Comm style:** `efc.operating_manual` is single source of truth.

### New deferred-conversation inbox items captured
- Plan Mission Control slow-decommission timeline.
- Design `info@apartmentsmart.com` handling (special-case shared mailbox).
- Phase 5 — Calendar integration design.
- Phase 1.D — modify OB Gmail ingester for full bodies + thread_id.

## Unreleased — 2026-05-07 (evening, decisions + design only — no plugin code change)

### Added
- **`docs/PHASE-4-INBOX-AI.md`** — full synthesis of the dormant Clearpath plugin into a Phase 4 build plan. Reads its 5,147-line PRD + 10 skills + 10 data seeds + 10 commands + MCP server. Maps Clearpath's design to Dave OS's `efc.*` Supabase schema, identifies what to absorb vs retire, lists 9 open questions for Dave to resolve, sequences a 6-milestone build order (M1 schema → M6 send capability).



### Decided (logged in `docs/ARCHITECTURE.md` § Decisions)
- **Routine output delivery:** Cowork blue-dot + macOS push. **No Telegram, no email.** Dave engages with the brief as a chat.
- **OpenBrain Gmail cadence:** changed from hourly to **every 1 minute** (operationally — `OnCalendar=*-*-* *:*:00` on the systemd timer + `expected_cadence_seconds=60` in `openbrain.connectors`). Run duration 5–9 sec; safe under Google quotas; `flock` prevents overlap.
- **Email management (Phase 4):** subsume the dormant Clearpath plugin into Dave OS. Its design is excellent; its JSON-file + tunneled-MCP implementation is wrong shape. Migration plan written into `docs/ARCHITECTURE.md` § Phase plan. Clearpath last activity was 2026-02-08; data files frozen at 5 template entries each; `mcp.davidlayfield.com` tunnel returns 404; no runtime.

### Deployed (operational, not in this repo)
- `dave-os-morning-briefing` scheduled task created (`~/.claude/scheduled-tasks/dave-os-morning-briefing/SKILL.md`). Cron: `0 7 * * *` local. Self-contained prompt — reads operating manual, inbox, overdues, journal, recent journal, yesterday's plan; produces a one-screen briefing; saves to `efc.daily_plans`.
- OpenBrain Gmail ingester timer on Ralph (`/etc/systemd/system/openbrain-gmail-ingest.timer`) updated to 1-minute cadence; old hourly version backed up at `.bak-hourly`.

### Captured for tomorrow's briefing
- Phase 1.C investigation (already inbox item `4706efbb…`).
- Phase 4 — Inbox AI / Clearpath subsumption — to be added as a new inbox item below.

## [0.4.0] — 2026-05-07 (afternoon)

### Added
- **`docs/PHASE-1C-INVESTIGATION.md`** — pre-staged diagnostic playbook for tomorrow's investigation of why `openbrain.memories.action_items` is sparse. Includes diagnostic SQL, decision tree, fall-back extractor design, escalation rule (Haiku → Sonnet at < 0.70 precision two weeks running), and a done-definition.
- **`efc.inbox_items.extraction_model`**, **`extraction_confidence`**, **`extracted_at`**, **`triage_outcome`** columns — forward-compat for poller-side LLM extraction and quality monitoring.
- **`efc.v_extractor_precision_weekly`** view — weekly precision per extraction_model: `kept / triaged`. Pre-built so the moment auto-extraction starts producing data, the rollup is queryable.
- Tomorrow's anchor goal staged as inbox item `4706efbb…` so `/briefing` surfaces Phase 1.C investigation as the morning must-do.

### Changed
- `skills/safety-and-boundaries/SKILL.md` — explicit authorization that the assistant *is* allowed to surface patterns warranting a clinical conversation, frame medication research as "worth asking your doctor about" (never "you should take X"), and operate as a high-level coach for organization/GTD/executive-function. Hard limits unchanged: no diagnosis, no prescription, no replacing clinicians. Aligns the skill with Dave's operating manual rule set this morning.

### Decided (logged in docs/ARCHITECTURE.md § Decisions)
- DaveOS and OpenBrain stay structurally separate (Option A). Tight integration via the bridge poller; separate schemas; separate repos; separate plugin distribution. They *narrate* as one product ("Dave OS") but don't share schemas or release cadence.

## [0.3.0] — 2026-05-07

### Added
- **`efc.journal_entries`** table — state observations distinct from action items (mood, energy, body/health/medication, food, relationships).
- **`efc.people`** table — relationship graph with last_interaction tracking, cadence_target_days, delegation_areas.
- **`efc.interactions`** table — per-exchange log; trigger auto-syncs `people.last_interaction_at`.
- **`efc.daily_reflections`** table — schema for the future autonomous nightly reflection job (L3).
- **`/journal`** command — frictionless capture for state observations; writes directly to `journal_entries`, bypasses inbox.
- `/triage` extended to route observations to `journal_entries` as a 6th option (do / defer / delegate / drop / waiting / **journal**).
- `docs/ARCHITECTURE.md` — full architecture, schema reference, phase plan, decision log.
- This `CHANGELOG.md`.

### Changed
- Two existing inbox items (the Chipotle/GLP-1 observation and the fade-note) migrated to `journal_entries` with topic tags.

### Notes
- L2 schema now totals **15 tables**, all RLS-enabled.
- The schema change to add `extraction_model` for poller-quality monitoring is **planned but not in this release** — pending Phase 1.C.

## [0.2.0] — 2026-05-07

### Added
- **`/capture`** — frictionless GTD capture; one INSERT into `efc.inbox_items`, one-line confirm.
- **`/inbox`** — show pending captures with relative timestamps and source labels.
- **`/triage`** — walk inbox items GTD-style (do / defer / delegate / drop / waiting), suggesting project / contexts / energy / time-estimate per item; mark inbox triaged on action.
- **`/briefing`** — morning brief reading inbox + overdues + active projects + operating manual + time-context window; produces a one-screen plan and saves it to `efc.daily_plans`.
- **`services/openbrain-poller/`** — Python systemd service that polls `openbrain.memories` every 5 minutes and forwards Dave-owned `action_items` into `efc.inbox_items`. Idempotent, owner-filtered, safe to re-run.
  - `deploy-to-ralph.sh` — one-shot install (venv, `/etc/efc/env`, systemd unit + timer, smoke run).

### Notes
- Poller is **deployed to Ralph but timer is not enabled** — pending fix to OpenBrain's own action_items extraction (only 2 of 188k memories have items populated).

## [0.1.0] — 2026-05-06

### Added
- Initial plugin: 9 skills, 10 commands, 5 sub-agents, 4 examples.
- Conversational coaching surface: `/daily-plan`, `/brain-dump`, `/start-task`, `/unstuck`, `/reframe`, `/shutdown`, `/weekly-review`, `/design-routine`, `/plan-project`, `/build-operating-manual`.
- Time-context hook (`UserPromptSubmit`) injects current local time + window per Dave's operating manual.
- `~/.claude/personal-operating-manual.md` — first version of Dave's living manual; later migrated to `efc.operating_manual` row.
- Plugin distributed via local marketplace (`.claude-plugin/marketplace.json`), installable in Claude Code CLI and Claude Cowork desktop.
