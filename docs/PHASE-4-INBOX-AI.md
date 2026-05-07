# Phase 4 — Inbox AI (Subsuming Clearpath into Dave OS)

_Synthesized 2026-05-07 from `/Users/davidlayfield/Desktop/Manual Library/code_projects/clearpath-plugin/` (frozen since 2026-02-08). Target: Dave OS `efc.*` schema in Supabase project `clawd-context`, executed by scheduled Claude Code routines._

---

## 1. The Clearpath vision (one paragraph)

Clearpath was an "email delegation engine" for a multi-account inbox where the inbox itself was the bottleneck. Instead of reading mail, run `/start` and get a ranked task list with YMYL alerts at the top, drafts pre-written for routine replies, and noise auto-archived. The system classifies every message into one of five buckets, extracts action items, scores them on a 6-dimension priority formula, learns sender importance from interaction patterns, clusters related threads into projects, and earns autonomy across three trust tiers (Observer → Drafter → Delegator) over the first 20 sessions. v1 was deliberately copy-paste-only (no auto-send) and session-based (nothing happened between `/start` runs). "Done" looked like four Success Criteria tests in PRD §14: the Morning Test (47-email Monday triaged in under 3 minutes with the tax deadline surfaced first), Autonomy Test, Trust Test, and Rescue Test (return from vacation, find the rent notice).

## 2. The 5-category email classification

**Categories:** ACTIONABLE, YMYL, INFORMATIONAL, NOISE, SPAM. Exactly one per email.

**Driving signals:**
- ACTIONABLE: question marks at Dave, request verbs (send/approve/review/sign/confirm/schedule), Dave in To not just CC, awaiting Dave's input
- YMYL: keyword + real-world consequence (see §4)
- INFORMATIONAL: "FYI"/"Heads up", Dave on CC only, status reports, confirmations
- NOISE: social media, marketing, generic newsletters, automated system pings
- SPAM: too-good-to-be-true, mismatched domain, phishing patterns

**Decision tree:** SPAM check → YMYL check → ACTIONABLE check → INFORMATIONAL check → default NOISE.

**Edge cases handled explicitly:** calendar invites (directed = ACTIONABLE; optional = INFORMATIONAL; gov inspection = YMYL); CC-only (default INFORMATIONAL unless Dave's name appears in body); forwards (depends on forwarder's note); thread continuations (downgrade to INFORMATIONAL once Dave has replied); attachments ("please review" = ACTIONABLE, "for your records" = INFORMATIONAL).

**Tie-breakers:** ACTIONABLE > INFORMATIONAL. INFORMATIONAL > NOISE. YMYL > ACTIONABLE. NOISE > SPAM (safer; recoverable).

This is the strongest part of Clearpath. Lift wholesale.

## 3. The scoring / prioritization engine

A 6-dimension weighted formula, all dimensions on 0.0–1.0:

```
priority_score =   urgency             * 0.25
                 + importance          * 0.25
                 + sender_authority    * 0.20
                 + deadline_proximity  * 0.15
                 + financial_impact    * 0.10
                 + context_richness    * 0.05
```

Dimension specs are banded (not gradient):

- **Urgency** — explicit deadline windows (24h=1.0, 48h=0.9, 1wk=0.7), urgency keywords (0.8), action verbs (0.7), no signal (0.5), FYI language (0.3)
- **Importance** — tenant safety (1.0), compliance (0.95), revenue (0.9), contract (0.9), routine ops (0.6), internal coord (0.5), personal (0.4)
- **Sender authority** — looked up in contacts; falls back to domain (.gov=0.9, financial=0.85, free email=0.4, suspicious=0.3)
- **Deadline proximity** — formula `0.5 + (2-D)/2 * 0.5` for D≤2 days, 0.5 otherwise
- **Financial impact** — banded by dollar amount (>$10K=1.0, $5–10K=0.9, etc.), +0.1 if "penalty/late fee/interest"
- **Context richness** — body length + attachments (+0.2) + thread history (+0.1) + specific details (+0.2) − vague (−0.2)

**Special rules applied after composite (in order):**
1. YMYL floor 0.85 (PRD §11 hardens this to severity-tiered: Critical 0.95, High 0.85, Medium 0.7)
2. Unknown sender + free email floor 0.45
3. CC-only ceiling 0.50 (exception: name in body)
4. Newsletter ceiling 0.20
5. Rule modifiers (capped ±0.30)
6. Score decay: tasks without deadlines lose 5%/day (display-time only)
7. Deadline boost: linear ramp to 1.0 in final 48h (display-time; YMYL decays at half rate)

PRD §8.5 also includes cold-start heuristics (To+0.15, CC−0.10, direct question +0.12, deadline +0.18, $ floors) for session 1 before contacts.json has data — and a contact-importance bootstrapping pass that scores from 7 days of history (thread depth, reply pattern, org domain, authority titles, volume).

This is durable. Clean, explainable, debuggable. Lift verbatim.

## 4. YMYL (Your Money Your Life) detection

**Triggers:** keyword scan (financial / legal / compliance / deadline / insurance / tax / housing-emergency lists, see PRD §11.2's 12-category table) AND real-world consequence context. Keyword alone is not enough; context alone is not enough.

**Two-pass design:** cheap deterministic keyword + pattern scan first (catches "$4,200 due Friday" or `sender@irs.gov` without LLM), then LLM confirmation that extracts severity (Critical/High/Medium), deadline, consequence, and recommended action.

**Action it takes:**
- Generates structured alert: WHAT / DEADLINE / CONSEQUENCE / NEXT STEP
- Always shown FIRST in `/inbox-start` output, before regular tasks
- Applies score floor (Critical 0.95 / High 0.85 / Medium 0.7)
- Cannot be auto-archived even by a matching rule (YMYL overrides rules)
- Never gets autonomous action even at Level 3 — always requires per-item Dave approval
- Decays at half rate; deadline-approach language escalates ("DEADLINE TOMORROW", "DEADLINE PASSED")
- Logged permanently to session log (audit trail)

**Why it exists:** "False positive is better than false negative." Missing a rent due notice or IRS letter has real cost. The whole architectural priority is "zero missed YMYL."

Both the categories and the override rules are durable.

## 5. Contact learning

`contacts.json` keyed by lowercase email, tracking name / organization / accounts seen on / interaction count / last interaction / importance score (0.0–1.0) / relationship tags / response pattern.

**Initial importance:** inferred from domain (.gov=0.9, bank=0.85, business=0.7, free email=0.4, unknown=0.5).

**Adjustment rules (rolling):**
- Dave acts within 4h: +0.05
- Dave acts within 24h: +0.02
- Dave ignores >72h: −0.02
- Dave classifies as noise/spam: −0.10
- Sender appears in YMYL/high-stakes context: +0.05
- Floor 0.1, cap 1.0

**Relationship inference:** auto-tagged from domain (.gov→government, internal domain match→internal, frequent invoices→vendor, recurring marketing→marketing). Multi-tag supported.

**Response pattern:** rolling avg of last 10 (task.acted_at − email.received_at), bucketed fast/normal/slow/delayed/ignored.

**Importance feeds directly into sender_authority dimension of scoring.** That's the load-bearing connection.

The PRD's bootstrapping pass (build initial scores from 7 days of history before session 1) is a thoughtful cold-start that we should preserve.

## 6. Newsletter extraction

**Whitelist-driven, not blacklist-driven.** `newsletters.json` carries `whitelist[]` (sender_pattern + optional subject_pattern), `interests[]` (10 keyword/topic strings — Dave's seed list includes affordable housing, LIHTC, AI agents, proptech, MD housing policy), `digests[]`, and `unreviewed_newsletters[]` for senders that look newslettery (List-Unsubscribe header, marketing tone) but aren't whitelisted.

**Pipeline:** during `/inbox-start` after classification, if NOISE/INFORMATIONAL AND sender matches whitelist pattern → reclassify as NEWSLETTER → parse body → score each story (HIGH/MEDIUM/LOW/SKIP) by keyword match against `interests[]` → save HIGH and MEDIUM stories → archive source email. If looks like newsletter but not whitelisted → log to `unreviewed_newsletters[]` for Monday brief.

**Digest format:** weekly grouped by interest topic, headline + source + 2-sentence summary, source breakdown footer.

**Whitelist management:** Monday 8AM brief surfaces unreviewed newsletters with options Add to whitelist / Unsubscribe / Ignore. After each digest: "Any interests to add or remove?" Stories Dave engages with reinforce matched interests; consistently-ignored interests get suggested for removal.

## 7. Unsubscribe management

`unsubscribe-queue.json`: `recommended_unsubscribes[]` (with sender, sample subject, times_seen, unsubscribe_link if any), `completed_unsubscribes[]`, `ignored_senders[]`, brief schedule.

**Detection:** during `/inbox-start`, if NOISE/SPAM and sender not on whitelist or already-completed/ignored → add to recommended (or increment times_seen).

**Auto-attempt (Chrome MCP):** if List-Unsubscribe URL exists, navigate, look for one-click confirm, click; if form/CAPTCHA/login → mark FAILED and route to manual list. Successful auto-unsubscribe → move to completed AND auto-create matching auto-archive rule for the sender (so any stragglers vanish).

**Weekly Monday 8AM brief:** auto-unsubscribed (this week) / recommended manual / previously failed (with link) / time-saved estimate.

PRD §12.2 honestly flags unsubscribe as the system's biggest open uncertainty — three-tier fallback depending on what's mechanically possible: best (MCP processes List-Unsubscribe directly), middle (compose/send unsub email), worst (provide Dave a clickable list).

## 8. Project detection

Auto-cluster threshold = 3+ emails sharing a signal. Five signals:

1. **Shared thread_id** (only counting ACTIONABLE/YMYL/INFORMATIONAL — exclude noise threads)
2. **Overlapping participants** (3+ emails with 2+ shared participant emails, excluding `noreply@` etc.)
3. **Property address match** (regex `\d+\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)*\s+(St|Ave|Rd|Blvd|Dr|Ln|Way|Ct)`, normalized across "Street"/"St" variants)
4. **Project keywords + same vendor domain** (keywords: construction, renovation, refinancing, compliance, inspection, etc.)
5. **Recurring subject prefix** (text before `: ` or ` - ` or ` | `, excluding "Re:"/"Fwd:")

**Auto-creation:** generate name from subject / address / org+topic / keywords. Generate description from first email + aggregated details. Link all matching `thread_ids` and `task_ids`. Set status = active.

**Lifecycle:** active → completed (all linked tasks acted) → stale (active + no activity 14+ days). Reopen if new task added to completed project.

The 3-signal threshold and 14-day staleness are reasonable but Dave-specific defaults — make them configurable in Dave OS.

## 9. Task extraction

**When:** ACTIONABLE or YMYL only.

**Components:**
- **Title:** imperative verb + object, ≤60 chars ("Review contract for 123 Main St", not "Contract")
- **Description:** full email context including amounts/dates/parties/attachments
- **Deadline:** parsed to ISO 8601 from "by Friday", "EOD", "ASAP" (→ +48h), explicit dates
- **Source tracking:** message_id, account, sender, sender_email
- **Initial status:** `waiting`

**Deduplication (3-check cascade):**
1. Exact `source_email_id` match → skip (already a task)
2. Same `thread_id` → update existing task; append `[UPDATE 2026-02-06]` note; refresh deadline if changed
3. Same sender_email + ≥80% fuzzy title match → update existing task

**Project linking:** after task creation, scan active projects for thread/participant/property/keyword match; if found, push task_id to project and set task.project_id.

**Multiple-actions-in-one-email rule:** single comprehensive task if related (same deadline/stakeholder), split if independent (different deadlines, one is YMYL and other isn't).

**Auto-archive after extraction:** task preserves all needed context, source can be archived, inbox stays clean.

## 10. Data schemas — durable design vs JSON-file incidentals

| Clearpath file | Durable design | Postgres mapping in Dave OS |
|---|---|---|
| **email-log.json** | Append-only dedup log keyed on Gmail message_id; account, thread_id, sender, classification, ymyl_alert object, rule_hits[], task_id link | New `efc.inbox_email_log`. Unique index on (account, message_id). |
| **tasks.json** | id / title / description / source_email_id / source_account / sender / sender_email / deadline / project_id / status (waiting/drafted/acted) / priority_score / score_dimensions{6} / score_reason / draft{text,created_at,status} | Extend existing `efc.tasks`. Add: source_email_id, source_account, priority_score, score_dimensions jsonb, score_reason text, draft jsonb, ymyl_classification text, deadline timestamptz |
| **contacts.json** | email key / name / organization / accounts_seen_on[] / interaction_count / last_interaction / importance_score / relationship_tags[] / response_pattern | Extend existing `efc.people`. Add: email_normalized text unique, importance_score numeric, relationship_tags text[], response_pattern text, interaction_count int, accounts_seen_on text[] |
| **projects.json** | id / name / description / email_thread_ids[] / participant_emails[] / task_ids[] / status (active/completed/stale) | Use existing `efc.projects`. Add columns email_thread_ids text[], participant_emails text[]. Tasks already FK to project. |
| **rules.json** | id / type (auto_archive\|auto_label\|priority_boost\|priority_suppress\|auto_draft\|auto_unsubscribe) / condition jsonb / action jsonb / active / times_applied / last_applied | New `efc.inbox_rules` |
| **session-log.json** | session_id / timestamp / counters / rules_fired[] / duration_seconds / autonomy_level | New `efc.inbox_sessions` |
| **newsletters.json** | whitelist[] / interests[] / digests[] / unreviewed_newsletters[] | Three new tables: `efc.newsletter_sources`, `efc.newsletter_interests`, `efc.newsletter_digests` |
| **unsubscribe-queue.json** | recommended[] / completed[] / ignored[] | New `efc.unsubscribe_queue` with status enum (recommended/completed/ignored) |
| **user-profile.json** | identity / companies / family / employees / interests / goals / preferences / key_contacts / properties / software / recurring_tasks | Already in `efc.operating_manual`. Reconcile rather than rebuild. Onboarding flow can populate it. |
| **credentials.json** | github.token + github.repo | **Drop.** `~/.keys/keys.txt` and Mission Control replace this. |

**Incidental to JSON files (drop):** atomic-write-via-rename, `next_id` counters, `_schema`/`_description` self-documenting fields, JSON-repair-on-corrupt logic, append-only file rotation strategies (PRD §12.3), the `<workspace>/clearpath/` path convention, GitHub credential dance.

## 11. User-facing commands & their outputs

| Cmd | Produces |
|---|---|
| `/inbox-start [account]` | "Scanning [X] unread across [Y] accounts" → "[N] new to process" → YMYL alerts (full WHAT/DEADLINE/CONSEQUENCE/NEXT STEP block per alert) → Top 10 tasks ranked by score → Session summary → "What would you like to tackle first?" |
| `/inbox-tasks [filter]` | Table: rank / score / title / sender / deadline / status. Detail view on selection: full email body, attachments, project link, draft if any, action menu. |
| `/inbox-projects [status]` | Table: project / tasks count / next deadline / top priority. Detail view: status, dates, participants, threads, tasks split by status, recent activity. |
| `/inbox-update [id\|title\|rank] [status]` | Confirms transition, +0.02 to sender importance, project update line, archive prompt. |
| `/inbox-review [filter]` | One draft at a time: TASK header, ORIGINAL EMAIL, GENERATED DRAFT, Actions: approve\|edit\|discard\|skip\|stop. |
| `/inbox-rules [action] [id]` | List with hit counts. add is interactive. edit/delete/disable/enable/test all supported. |
| `/inbox-report [period]` | Plain-English brief: inbox activity / classification breakdown / task metrics / draft performance / automation efficiency / top senders / 3–4 actionable recommendations. |
| `/inbox-digest [week\|today]` | Stories grouped by matched interest topic, headline+source+summary, source breakdown footer. |
| `/inbox-unsubscribe [list\|brief\|from sender]` | List view sorted by frequency. Brief is the full Monday 8AM format. |
| `/inbox-onboarding [continue\|update]` | Conversational 7-phase interview, populating `efc.operating_manual`. Resumable. |

(Naming convention: prefix with `inbox-` so they don't collide with EFC's existing commands.)

## 12. The clearpath-identity skill — keep separate from EFC

Identity = "email delegation engine"; mission = chaotic inboxes → ranked task list. Personality: efficient, proactive, protective. Plain English. Honest about limits. Asks when uncertain.

**Voice rules and draft style** (short sentences, "Thanks" frequent, signs "Best, Dave" / "Thanks, Dave", `[PLACEHOLDER: description]` for fill-ins, structure: greeting → direct response → next steps → closing, mirror sender's formality, ≤3–5 sentences).

**Six safety rules** (override everything): no auto-create rules without approval; no auto-send (v1); no permanent delete without confirmation; never skip YMYL; auto-archive/auto-label safe after first approval; when in doubt, ask.

**Three autonomy levels** (Observer 1–5 / Drafter 6–20 / Delegator 20+). Trust earned via session count + draft acceptance rate (50%+ over 5 sessions). YMYL never gets autonomous action even at Level 3.

**Recommendation:** Dave OS already has `executive-function-copilot` as the coaching surface (gentle, ADHD-aware, anti-toxic-positivity). **Keep the inbox-AI voice separate** — it's execution-focused (terse, action-first, deadline-aware) versus EFC's process-focused tone. The autonomy-level concept and the safety rules absolutely belong in Dave OS at the system level (operating contract for any agent that touches mail). The draft style guide should live in `efc.operating_manual` so it informs anything that drafts in Dave's voice.

## 13. Implementation choices to retire

- JSON-file persistence (all 10 files)
- `<workspace>/clearpath/` path convention
- Cloudflare-tunneled custom Gmail MCP at `mcp.davidlayfield.com/mcp`
- 6-account custom OAuth/token store — Mission Control already has tokens
- `credentials.json` GitHub-token-in-remote-URL pattern
- Cowork-session-as-runtime assumption (PRD §10.1) — Dave OS scheduled routines invert this
- Append-only files with rotation strategy (PRD §12.3)
- `autonomy.json` separate file — collapse into `efc.operating_manual` or `efc.poller_state`
- `clearpath.plugin` tarball + `.claude-plugin/plugin.json` distribution
- External sync protocol scaffolding (sync_id/sync_status/sync_target/external_id) — defer until real demand

## 14. Implementation choices to absorb

- The 5-category classification with decision tree, edge cases, tie-breaker rules
- The 6-dimension scoring formula with banded inputs and 7 special rules (incl. cold-start heuristics and contact bootstrapping)
- YMYL: 12-category table, two-pass detection, severity-tiered floors, permanent log, escalating deadline language, override-rules-not-rules-override-it
- The 3-state task model (waiting / drafted / acted)
- Contact importance learning loop (+0.05 fast / +0.02 normal / −0.02 ignored / −0.10 noise)
- Project auto-detection signals (5 clustering rules, 3+ threshold, 14-day stale rule) and lifecycle
- Newsletter whitelist + interests model with HIGH/MEDIUM relevance scoring and weekly digest
- Three-tier autonomy escalation gated on session count + draft acceptance rate
- Six safety rules as operating contract (especially "YMYL never gets autonomous action, even at Level 3")
- Onboarding's 7-phase structure as a one-time bootstrap of `efc.operating_manual`
- Catch-up batched processing for vacation-backlog scenarios (PRD §12.7)
- Append-only email-log with classification + ymyl_alert + rule_hits + task_id (perfect dedup design)
- Score decay (5%/day) and deadline boost (linear 48h ramp) as display-time-only transforms
- Output formatting conventions for `/inbox-start`, `/inbox-tasks`, `/inbox-projects`, `/inbox-report`, YMYL alerts

## 15. Open questions — RESOLVED 2026-05-07 evening

| # | Question | Resolution |
|---|---|---|
| Q1 | Auto-send | **Copy-paste only at first.** Graduate to auto-send for low-stakes categories after 30 days of seeing the system draft replies you'd actually send. YMYL stays manual forever. |
| Q2 | Active accounts | **5 accounts in Dave OS firehose:** gsh, ai, dflayfield, as, urbanorigin. **`info@apartmentsmart.com` deliberately excluded** from OpenBrain (huge volume, shared mailbox); needs its own design (separate session). |
| Q3 | Mission Control vs direct Gmail API | **Mission Control is being decommissioned.** Email read/send/archive lives in Claude (plugin commands or routines). OAuth tokens stored in Supabase Vault (`vault.secrets`) — confirmed enabled on the project. Migration is slow, not immediate; Mission Control stays running until Dave OS subsumes each module. |
| Q4 | OpenBrain overlap / full bodies | **Modify OpenBrain Gmail ingester to capture full bodies AND preserve thread structure** (`thread_id` linking). Phase 1.D prerequisite. Already captured as inbox items 4417c2bf and ___ (thread). |
| Q5 | Auto-pull cadence | **Every 5 minutes, silent background.** Matches OB ingester. Only the morning brief notifies; auto-pull processes silently. |
| Q6 | Newsletter whitelist seed | **Confirmed: 6 newsletters** (AI Secret, Robotics Herald, Bay Area Letters, TechCrunch, Axios Morning, Axios AI). Need plugin commands to add/remove/list/suggest — delivered in M5. |
| Q7 | YMYL false-positive ceiling | Defaults fine to start. Revisit after first weekly `/inbox-report`. |
| Q8 | Calendar integration | **Phase 5 — own session.** Calendar moves into Dave OS as Mission Control retires. Direct Google Calendar API + OAuth tokens in `vault.secrets`. Not part of Phase 4. |
| Q9 | Communication style single source | **`efc.operating_manual` is the source.** Inbox AI's drafting reads from operating manual; no separate copy. |

## 15a. Mission Control retirement plan (added 2026-05-07)

Mission Control is being decommissioned. Migration is slow — leave MC as-is, replace each module piece-by-piece as Dave OS subsumes it.

| MC module | Dave OS successor | Status |
|---|---|---|
| Email (read/list/search) | Plugin command + routine; OAuth in `vault.secrets` | Phase 4 M2/M3 |
| Email (send) | Plugin command, gated on autonomy level | Phase 4 M6 |
| Email (archive / mark / label) | Plugin commands | Phase 4 M2 |
| Calendar | Plugin command + routines | **Phase 5 — own session** |
| Tasks | `efc.*` schema | Already done |
| Finance / Plaid | Dave OS personal-finance surface; same Plaid app, different consumer | Phase 6 — Dave wants this in Claude |
| News | Newsletter digest + routines | Phase 4 M5 |
| Briefings | `dave-os-morning-briefing` routine | Already done |
| Memory | OpenBrain | Already done |
| Projects | `efc.projects` | Already done |

**Open questions for the MC-retirement session:**
- Where does Cowork's built-in Gmail integration sit vs. our own OAuth-in-vault path? (May obviate token migration.)
- Plaid migration: does Dave OS take over financial routines (categorize transactions, surface anomalies, weekly cashflow brief)? Or just decommission Plaid altogether and re-decide finance later?
- News module — what's MC currently doing for news that the newsletter digest doesn't cover?
- Cleanup timeline: when does MC actually shut down vs. just stop being the source-of-truth?

## 16. Phase 4 build order

Six milestones. M1–M3 are MVP; M4–M6 are extensions. Do not try to ship the full PRD in one pass.

### M1 — Schema + ingestion (foundation) — **✅ SHIPPED 2026-05-07 evening**
- ✅ Created `efc.inbox_email_log`, `efc.inbox_rules`, `efc.inbox_sessions`, `efc.newsletter_sources`, `efc.newsletter_interests`, `efc.newsletter_digests`, `efc.unsubscribe_queue`
- ✅ Extended `efc.tasks` with `source_email_id`, `source_account`, `sender_name`, `sender_email`, `thread_id`, `priority_score`, `score_dimensions`, `score_reason`, `draft`, `ymyl_classification`, `ymyl_alert`
- ✅ Extended `efc.people` with `email_normalized`, `importance_score`, `relationship_tags`, `response_pattern`, `interaction_count`, `accounts_seen_on`, `organization`
- ✅ Seeded 6 newsletter sources + 10 interest topics (per Q6)
- ✅ All RLS-enabled, single-user permissive policies
- ⏭️ Single-account fetch loop verification → moved to M2 (depends on OAuth wiring)

### M1.5 — OpenBrain ingester upgrade (Phase 1.D, Dave-flagged prerequisite)
- Modify `/home/ubuntu/openbrain/connectors/gmail/openbrain_gmail_ingest.py` on Ralph:
  - Capture **full email bodies** (currently snippets-only; max 3KB; need full)
  - **Preserve thread structure** — populate `openbrain.memories.thread_id` so a single query returns "every message in this thread, in order, both directions"
- Backfill thread_id on existing 154k+ gmail memories where derivable
- Add `urbanorigin` (dave@urbanorigin.io) to the ingester's account list if not already present
- **Explicitly exclude `info@apartmentsmart.com`** from the ingester's account list (separate session for that mailbox)

### M2 — Classification + YMYL + scoring (the brain)
- Port email-classification skill as a system prompt section for the inbox-process routine
- Port YMYL detection (two-pass: keyword first, LLM confirm) — non-negotiably first-class
- Port the 6-dimension scoring engine, 7 special rules, cold-start heuristics
- Wire score_dimensions/score_reason onto tasks
- Single-account end-to-end: fetch unread → classify → YMYL detect → score → write tasks
- Build `/inbox-start` slash command (or routine equivalent)
- **MVP success:** Morning Test (PRD §14.1) passes on gsh account

### M3 — Multi-account + contact learning + project linking
- Expand to all active accounts (per Q2 resolution)
- Port contact-learning loop with importance score adjustments tied to task acted_at
- Port project-detection signals (5 clustering rules) reading from existing `efc.projects`
- Port task deduplication (3-check cascade)
- Port `/inbox-tasks`, `/inbox-projects`, `/inbox-update`, `/inbox-review` commands
- **MVP success:** Trust Test passes — score correlates with Dave's actual action order

### M4 — Rules engine + automation
- Port the rule schema (auto_archive, auto_label, priority_boost, priority_suppress, auto_draft, auto_unsubscribe)
- Port `/inbox-rules` command (list, add, edit, delete, disable, test)
- Port the 4 built-in rules on first-run (LinkedIn, social media, gov boost, financial boost)
- Wire rule evaluation into the pipeline (before classification, can short-circuit auto_archive)
- Add the autonomy-level gate (Observer/Drafter/Delegator) — block auto-archive/auto-draft until Dave approves at first-occurrence per sender

### M5 — Newsletter + unsubscribe + reporting
- Port newsletter-extraction, whitelist + interests, weekly digest generation
- Port unsubscribe-manager with three-tier fallback (per PRD §12.2)
- Build `/inbox-digest`, `/inbox-unsubscribe`, `/inbox-report` commands
- Schedule the Monday 8AM brief as a Claude Code routine on Ralph
- Schedule the auto-pull (cadence per Q5)

### M6 — Onboarding + send capability + integrations (defer)
- Port the 7-phase onboarding skill, writing to `efc.operating_manual`
- Decide auto-send (per Q1): enable Mission Control direct send for Drafter+Delegator levels, gated on YMYL exclusion
- Optional: external task sync if anything actually needs it
- Optional: calendar integration (per Q8)

**Cut for now:** the Cowork-plugin-distribution scaffolding, the cloudflare tunnel, the `<workspace>/clearpath/` file path convention. None of these survive on Dave OS architecture.

---

## Source files of record

- PRD: `/Users/davidlayfield/Desktop/Manual Library/code_projects/clearpath-plugin/clearpath-plugin-prd.md`
- Skills: `/Users/davidlayfield/Desktop/Manual Library/code_projects/clearpath-plugin/plugin/skills/{clearpath-identity,email-classification,scoring-engine,ymyl-detection,contact-learning,newsletter-extraction,unsubscribe-manager,project-detection,task-extraction,onboarding,data-management}/SKILL.md`
- Commands: `/Users/davidlayfield/Desktop/Manual Library/code_projects/clearpath-plugin/plugin/commands/{start,onboarding,digest,tasks,projects,rules,review,update,report,unsubscribe}.md`
- Data seeds: `/Users/davidlayfield/Desktop/Manual Library/code_projects/clearpath-plugin/plugin/data/*.json`
- v1 archive: `/Users/davidlayfield/Desktop/Manual Library/code_projects/clearpath-plugin/plugin/rules/RULES.md` (1,794 lines, kept as cross-reference)
