# Changelog

All notable changes to this project go here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

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
