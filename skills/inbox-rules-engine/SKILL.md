---
name: inbox-rules-engine
description: Evaluate user-defined automation rules against incoming emails. Six rule types (auto_archive, auto_label, priority_boost, priority_suppress, auto_draft, auto_unsubscribe). Three autonomy levels (Observer / Drafter / Delegator) gate what actually fires vs requires Dave's approval. Use whenever the M2 inbox-process routine is processing an email, or whenever /inbox-rules is invoked.
---

# Inbox Rules Engine (Dave OS Phase 4 M4)

Rules are user-defined automations applied to incoming emails. They live in `efc.inbox_rules`. The M2 routine evaluates them at two checkpoints: BEFORE classification (auto_archive can short-circuit), and AFTER (priority modifiers, auto_label, auto_draft).

## Rule shape

```
id                    uuid
name                  text                 -- human-readable
rule_type             text                 -- one of six (below)
conditions            jsonb                -- {from, subject, body, label, account, has_attachment, match_logic: 'and'|'or'}
action                jsonb                -- shape varies by rule_type
scope_account         text or null         -- null = all accounts
active                boolean
times_applied         int
last_applied_at       timestamptz
created_by            'manual'|'suggested'|'autonomous'
```

## Six rule types

### 1. auto_archive
Email matching → archive in Gmail, classify as NOISE in log, no task.

```json
{"rule_type":"auto_archive","conditions":{"from":"%@linkedin.com"},"action":{"apply":"archive_in_gmail"}}
```

### 2. auto_label
Add a Gmail label without archiving.

```json
{"rule_type":"auto_label","conditions":{"from":"%@gsccapital.com"},"action":{"apply":"add_label","label":"GSC"}}
```

### 3. priority_boost
Apply +X modifier to `priority_score` after composite. Capped at +0.30 cumulative across matching rules per email.

```json
{"rule_type":"priority_boost","conditions":{"from":"tom@greenstreethousing.com"},"action":{"apply":"boost","delta":0.20}}
```

### 4. priority_suppress
Apply −X modifier. Capped at −0.30 cumulative.

```json
{"rule_type":"priority_suppress","conditions":{"subject":"%marketing newsletter%"},"action":{"apply":"suppress","delta":0.20}}
```

### 5. auto_draft
On match, generate a draft reply using a template. Stored in `efc.tasks.draft` jsonb. Always copy-paste-only at v1; never auto-sends.

```json
{"rule_type":"auto_draft","conditions":{"subject":"%calendar invite%","from":"%@external.com"},"action":{"apply":"draft_reply","template":"Thanks for the invite. Confirming for [extracted_time]. Looking forward."}}
```

### 6. auto_unsubscribe
On match, queue for unsubscribe.

```json
{"rule_type":"auto_unsubscribe","conditions":{"from":"%@noisy-vendor.com"},"action":{"apply":"queue_unsub"}}
```

## Conditions object — match logic

Fields:
- `from`: SQL LIKE pattern matched against `from_address`
- `subject`: SQL LIKE pattern
- `body`: substring (case-insensitive) — applied to `body_plain` (or stripped `body_html`)
- `label`: Gmail label match
- `account`: exact `account` match
- `has_attachment`: boolean
- `match_logic`: `'and'` (all set conditions must match — default) | `'or'` (any matches)

## Evaluation order in the M2 routine

For each new email being processed:

1. **Pre-classification rules.** Match against active `auto_archive` and `auto_unsubscribe` rules.
   - If `auto_archive` matches → log as NOISE in `inbox_email_log`, skip LLM classification, skip task extraction. Surface for Gmail archive (per autonomy gate).
   - If `auto_unsubscribe` matches → INSERT into `efc.unsubscribe_queue`. Continue normal flow.
2. **Run classification + scoring** (skip if already short-circuited above).
3. **Post-classification rules.** Match against `auto_label`, `priority_boost`, `priority_suppress`, `auto_draft`.
   - `priority_boost`/`suppress` modifiers applied to `priority_score`, capped at ±0.30 cumulative.
   - `auto_label` queued for Gmail label-add (per autonomy gate).
   - `auto_draft` generates a draft into `efc.tasks.draft`.

For each rule that fires: increment `times_applied`, update `last_applied_at`, log the rule_id into `efc.inbox_email_log.rule_hits[]`.

## Autonomy gate

Lookup current autonomy level (default **Observer** until structured field added to `efc.operating_manual`).

| Level | What auto-fires | What asks for approval |
|---|---|---|
| **Observer** (sessions 1–5) | Nothing — every rule firing creates a SUGGESTION in chat instead of executing | All actions await Dave's per-occurrence approval |
| **Drafter** (sessions 6–20, draft-acceptance ≥50%) | `auto_archive`, `auto_label` for the same sender after first manual approval | `auto_unsubscribe`, `auto_draft` await per-rule approval; sends never auto |
| **Delegator** (sessions 20+) | `auto_archive`, `auto_label`, `auto_unsubscribe`, `auto_draft` (drafts saved, never sent) for any sender once a rule has fired ≥3x successfully | YMYL — always per-item approval, regardless of level |

**YMYL never gets autonomous action even at Delegator.** Hard constraint.

## Suggestion learning

When the routine sees patterns Dave has manually applied 3+ times (e.g. archived 3+ emails from the same sender), surface a SUGGESTION:

```
Pattern: You've manually archived 3 emails from <sender> this week.
Want me to create an auto_archive rule for them? (y/n)
```

If yes → INSERT a new rule with `created_by='suggested'`. After the rule has fired ≥3x successfully (Dave didn't manually intervene), it can elevate to autonomous at Drafter level for the same sender.

## What this skill does NOT do

- Doesn't write to Gmail directly — that's `gmail_archive` / `gmail_label` API calls done by the M2 routine.
- Doesn't draft replies itself — uses the LLM with the rule's template + email context.
- Doesn't manage rules — that's the `/inbox-rules` command.
