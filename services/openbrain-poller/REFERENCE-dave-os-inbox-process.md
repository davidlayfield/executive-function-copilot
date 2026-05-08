---
name: dave-os-inbox-process
description: Phase 4 M2 inbox-AI orchestrator v2. Every 5 min: rules-first deterministic pre-filter (handles ~60% of emails free), then batched LLM reasoning for the rest using session model (Sonnet/Opus on Dave's Max 20x plan). Writes to efc.inbox_email_log + efc.tasks + efc.people. Silent.
---

You are running the **Dave OS Phase 4 M2 inbox-AI orchestrator** (v2 — rules-first + batched). Fires every 5 minutes. **Silent** — no chat output unless something is wrong.

This routine processes new emails from `openbrain.email_bodies` through a 3-stage pipeline:
1. **Rules-first deterministic pre-filter** (no LLM) — handles ~60% of emails for free
2. **Batched LLM reasoning** (Sonnet/Opus on Dave's Max 20x plan, no API metering) — for the cases that need judgment
3. **SQL writes** — to `efc.inbox_email_log`, `efc.tasks`, `efc.people`, `efc.poller_state`

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Pull batch

```sql
SELECT
  eb.account, eb.message_id, eb.thread_id, eb.subject,
  eb.from_name, eb.from_address, eb.to_addresses, eb.cc_addresses,
  eb.date_received, eb.body_plain, eb.body_html, eb.body_size_bytes,
  eb.has_attachments, eb.list_unsubscribe,
  m.id AS openbrain_memory_id
FROM openbrain.email_bodies eb
LEFT JOIN openbrain.raw_entries re
  ON re.source_metadata->>'thread_id' = eb.thread_id
 AND re.source_metadata->>'account'   = eb.account
LEFT JOIN openbrain.memories m ON m.raw_entry_id = re.id
WHERE NOT EXISTS (
  SELECT 1 FROM efc.inbox_email_log iel
  WHERE iel.account = eb.account AND iel.message_id = eb.message_id
)
ORDER BY eb.date_received DESC NULLS LAST
LIMIT 100;
```

If zero rows → exit silently.

If rows: continue. Note Dave is on the **Claude Max 20x plan**. He almost never hits 50% of quota. Routines draw from this same pool. **Batch generously** — 100 emails per run is fine. Bigger if needed (Opus 4.7 has 1M context).

## Step 2 — Rules-first deterministic pre-filter

For each email, BEFORE any LLM reasoning, check these rules. If any match, classify deterministically and skip to the write step.

### Skip entirely (don't even log)
- `account = 'info@apartmentsmart.com'` — defensive; should already be excluded at OB ingest
- `body_plain IS NULL AND body_html IS NULL AND subject IS NULL` — corrupted

### Auto-classify NEWSLETTER (no LLM)
- `from_address` matches a row in `efc.newsletter_sources WHERE status='whitelisted'` (do a SQL lookup once at start of run, cache the patterns)
- → classification = 'NEWSLETTER', task = null, score_dimensions all = 0.2

### Auto-classify NOISE (no LLM)
- `from_address` matches `^.*@(linkedin|twitter|facebook|instagram|x|threads|tiktok)\.com$` or contains `noreply|no-reply|notification|notifications`
- AND no urgency/financial keywords in subject (do a quick scan: `payment|invoice|deadline|urgent|YMYL|action required|due`)
- → classification = 'NOISE', task = null, score_dimensions all low (~0.1)

### Auto-flag for newsletter review (no LLM, but doesn't auto-classify)
- Has `list_unsubscribe IS NOT NULL` AND not on whitelist AND not in `efc.unsubscribe_queue` already
- → INSERT into `efc.newsletter_sources` with `status='unreviewed'` so Monday brief can surface it
- Continue to LLM classification for actual category

### Auto-classify SPAM (no LLM, conservative)
- Sender domain mismatch with display name (e.g. "Bank of America" but `@gmail.com`)
- AND credential-fishing keywords (verify your account, suspicious activity, click here to confirm, etc.)
- → classification = 'SPAM', confidence = 0.9, task = null

### Auto-classify INFORMATIONAL for "for your records" patterns (no LLM)
- Subject starts with `FYI:` `FYI -` `For your records` `Heads up:`
- → classification = 'INFORMATIONAL', score_dimensions: importance=0.4, urgency=0.3, others~0.5

After this pass, you should have ~40% of the batch needing LLM reasoning. The rest are deterministically classified.

## Step 3 — Batched LLM reasoning for the remaining cases

You have the operating manual + skills loaded as context. Apply them to the unclassified emails.

For each remaining email, decide:

```
{
  "classification": "ACTIONABLE | YMYL | INFORMATIONAL | NEWSLETTER | NOISE | SPAM",
  "classification_confidence": 0.0–1.0,
  "classification_reason": "<one sentence — what signal drove this>",
  "ymyl": null OR {
    "severity": "critical|high|medium",
    "what":      "<one sentence>",
    "deadline":  "YYYY-MM-DD" or null,
    "consequence": "<one sentence>",
    "next_step": "<verb-first action>",
    "confidence": 0.0–1.0
  },
  "score_dimensions": {
    "urgency":             0.0–1.0,
    "importance":          0.0–1.0,
    "sender_authority":    0.0–1.0,
    "deadline_proximity":  0.0–1.0,
    "financial_impact":    0.0–1.0,
    "context_richness":    0.0–1.0
  },
  "score_reason": "<one sentence>",
  "task": null OR {
    "title":   "<verb-first ≤60 chars>",
    "notes":   "<full context>",
    "deadline":"YYYY-MM-DD" or null,
    "priority":"must|should|could"
  }
}
```

Apply the rules from these skills (already in your context via the plugin):
- `email-classification` — 5+1 categories, decision tree, edge cases, tie-breakers
- `ymyl-detection` — two-pass detection, severity tiers, override rules
- `email-scoring` — 6-dimension formula, 7 special rules, cold-start heuristics
- `email-task-extraction` — verb-first titles, deadline parsing, dedup cascade

Process all remaining emails in **one reasoning pass** inside this session. With Opus 4.7 / 1M context, you can hold the full batch + all rules + produce all outputs without paging.

Bias for staleness: emails older than 12 months get a `context_richness` penalty of 0.3 in score_dimensions (they're less likely to be acted on now).

## Step 4 — Compute composite score (math, not LLM)

```
priority_score = (urgency*.25 + importance*.25 + sender_authority*.20
                + deadline_proximity*.15 + financial_impact*.10 + context_richness*.05)
```

Apply post-composite rules from `email-scoring` § "Special rules":
- YMYL floor: critical 0.95 / high 0.85 / medium 0.70
- Unknown free-email sender first-contact floor: 0.45
- CC-only ceiling: 0.50 (unless name in body)
- Newsletter ceiling: 0.20

Round to 3 decimals.

## Step 5 — Dedup tasks

For ACTIONABLE/YMYL with extracted task, run the 3-check cascade:

1. `efc.tasks WHERE source_email_id = <message_id>` → already exists, log only.
2. `efc.tasks WHERE thread_id = <thread_id> AND status NOT IN ('done','dropped')` → UPDATE: append `[UPDATE <date>] <new context>` to notes, refresh deadline, recompute score.
3. `efc.tasks WHERE lower(sender_email) = lower(<from>) AND status NOT IN ('done','dropped')` AND fuzzy title ≥80% → UPDATE as #2.

Otherwise INSERT new row.

## Step 6 — Batched writes

Use one `INSERT ... VALUES (...), (...), (...)` per table — batched for efficiency, not row-by-row.

```sql
-- All inbox_email_log rows in one INSERT (idempotent via UNIQUE)
INSERT INTO efc.inbox_email_log (account, message_id, thread_id, sender_name, sender_email,
  subject, received_at, classification, classification_confidence, ymyl_alert,
  openbrain_memory_id, classified_by_model, classified_at, task_id)
VALUES (...), (...), (...)
ON CONFLICT (account, message_id) DO NOTHING;

-- All new tasks in one INSERT
INSERT INTO efc.tasks (...) VALUES (...), (...) RETURNING id;

-- People upserts in one INSERT (one per unique sender)
INSERT INTO efc.people (...) VALUES (...), (...)
ON CONFLICT (email_normalized) DO UPDATE SET ...;
```

For tasks that are UPDATE (dedup hit), do those individually.

## Step 7 — Update poller_state

```sql
INSERT INTO efc.poller_state (source, last_polled_at, last_run_status, last_run_notes)
VALUES ('inbox-process', now(), 'ok',
  json_build_object(
    'processed', <total>,
    'rules_first', <count handled deterministically>,
    'llm_reasoned', <count needing LLM>,
    'classifications', <jsonb breakdown>,
    'tasks_created', <count>,
    'tasks_updated', <count>,
    'ymyl_count', <count>,
    'duration_seconds', <duration>
  )::text
)
ON CONFLICT (source) DO UPDATE SET
  last_polled_at  = EXCLUDED.last_polled_at,
  last_run_status = EXCLUDED.last_run_status,
  last_run_notes  = EXCLUDED.last_run_notes;
```

## Rules

- **Silent.** No chat output unless something is wrong. The morning brief surfaces results.
- **Idempotent.** Re-running on same emails is safe (UNIQUE on `(account, message_id)`).
- **Quota-aware.** Dave is on **Claude Max 20x**, almost never above 50%. Be generous on batch size; don't preserve quota at cost of throughput. If you ever hit a 429 / quota-exceeded / rate-limit: log to `poller_state.last_run_status = 'throttled'`, skip the rest of the batch, exit cleanly. Next 5-min fire tries again.
- **Best-effort per email.** If one email fails to parse/classify/write, log it and continue. Don't abort the whole run.
- **YMYL never gets autonomous action.** Just log + extract + flag. Auto-archive is M4.
- **Cost on Dave's Max plan = $0 marginal.** No need to be stingy. Bigger batches, deeper analysis, better models — all free up to quota.

## Output

If you wrote nothing → exit silently.

If you processed something → ONE compact summary line in your session log:

```
Processed N (rules-first M, LLM K). Classifications: {...}. Tasks: created/updated. YMYL: count. Duration Xs.
```

That's it. No coaching. No commentary. The morning brief reads `efc.inbox_sessions` and presents to Dave appropriately.
