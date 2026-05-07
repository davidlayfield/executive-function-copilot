# Phase 1.C — OpenBrain Extraction Investigation

_Pre-staged for the next peak window. Goal: figure out why `openbrain.memories.action_items` is populated on only 2 of 188,228 rows and either fix the source pipeline or build a fallback in the EFC poller._

---

## What we know going in

- **Counts (as of 2026-05-07 16:00 EDT):**
  - 188,228 memories total in `openbrain.memories`.
  - 2 with `action_items` populated (jsonb non-null, non-empty array).
  - Last 8 weeks: 156,762 ingested, 2 with action_items.
  - The 2 hits were one each in week-of Mar 16 and week-of Apr 6. So extraction *has* run, but extremely sporadically.
- **Schema clue:** `openbrain` schema contains `enrichment_queue` and `ingest_runs` tables. There's almost certainly a worker designed to process new memories, populate `action_items`, and possibly other enrichment fields (`entities`, `topics`, `enrichment_status`, `enrichment_metadata`, `embedding`, `embedding_v2`).
- **EFC poller:** deployed on Ralph at `/home/ubuntu/efc/openbrain-poller/`, systemd unit + timer installed but **timer not enabled**. End-to-end pipeline confirmed working (it just has nothing to forward right now).

## Diagnostic queries — run these first

### 1. Inspect `enrichment_queue`

```sql
-- Schema
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema='openbrain' AND table_name='enrichment_queue'
ORDER BY ordinal_position;

-- Backlog size + status breakdown
SELECT
  count(*) AS total,
  count(*) FILTER (WHERE status = 'pending')    AS pending,
  count(*) FILTER (WHERE status = 'processing') AS processing,
  count(*) FILTER (WHERE status = 'done')       AS done,
  count(*) FILTER (WHERE status = 'failed')     AS failed,
  count(*) FILTER (WHERE status NOT IN ('pending','processing','done','failed')) AS other_status
FROM openbrain.enrichment_queue;

-- Adjust if status column doesn't exist; first query reveals the schema.

-- Recent activity
SELECT date_trunc('day', created_at) AS day, count(*)
FROM openbrain.enrichment_queue
WHERE created_at > now() - interval '30 days'
GROUP BY 1 ORDER BY 1 DESC;
```

### 2. Inspect `ingest_runs`

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema='openbrain' AND table_name='ingest_runs'
ORDER BY ordinal_position;

-- Last 20 runs
SELECT *
FROM openbrain.ingest_runs
ORDER BY created_at DESC
LIMIT 20;

-- Distribution of run statuses, last 30 days
SELECT date_trunc('day', created_at) AS day, status, count(*)
FROM openbrain.ingest_runs
WHERE created_at > now() - interval '30 days'
GROUP BY 1, 2 ORDER BY 1 DESC;
```

### 3. Cross-reference `enrichment_status` on memories

```sql
SELECT enrichment_status, count(*)
FROM openbrain.memories
WHERE created_at > now() - interval '60 days'
GROUP BY 1 ORDER BY 2 DESC;

-- Any memories pending enrichment that should have been processed?
SELECT count(*)
FROM openbrain.memories
WHERE created_at < now() - interval '24 hours'
  AND (enrichment_status IS NULL OR enrichment_status IN ('pending','queued'));
```

### 4. Look at the working examples

```sql
-- The 2 memories that DID get action_items extracted —
-- what's special about them? Different memory_type? Source?
SELECT id, memory_type, source, enrichment_status, enrichment_metadata,
       jsonb_array_length(action_items) AS n_actions,
       created_at
FROM openbrain.memories
WHERE jsonb_typeof(action_items) = 'array'
  AND jsonb_array_length(action_items) > 0;
```

## Decision tree from the diagnostic results

```
Backlog in enrichment_queue large? (e.g. >10k pending)
├── YES — worker stalled. Find it:
│         - Check Ralph: systemctl list-units '*openbrain*'; pgrep -af openbrain
│         - Check Mission Control / docker / cron for the enrichment worker.
│         - If found: restart, watch logs, confirm queue drains.
│         - If not found: worker was never running OR was deleted. Build it.
│
├── NO — workers running but only producing 2 actions across 188k.
│        Means the enrichment job runs but its action-item prompt is broken
│        / always-empty. Check: which model is it using? what's the prompt?
│        Likely fix: improve the extraction prompt, or backfill on existing
│        data.
│
└── ENRICHMENT_QUEUE EMPTY/UNUSED — worker concept exists but isn't wired.
    Fall back to EFC-side extraction: build a small extractor in the poller
    that uses Anthropic API (Haiku-class) to produce action_items at
    forward time. Track in efc.inbox_items.extraction_model.
```

## Fall-back plan: extractor inside the EFC poller

If OpenBrain's own pipeline can't be revived in <1 hour, switch lanes.

1. **Add Anthropic client to `services/openbrain-poller/poller.py`.**
   - `anthropic` to `requirements.txt`.
   - `ANTHROPIC_API_KEY` added to `/etc/efc/env` on Ralph (use `tools-scripts` key from `~/.keys/keys.txt`).

2. **Extraction prompt (system):**
   ```
   You are extracting Dave Layfield's personal action items from a memory.
   A memory is one of: an email, a transcribed call, an AI-chat exchange,
   a meeting summary, a YouTube transcript, a chat message.

   Rules:
   - Output JSON only. Schema: {"actions":[{"task":"...","owner":"USER|null|<name>","due":"YYYY-MM-DD|null","confidence":0.0-1.0}], "skip":boolean}
   - Set skip=true ONLY if the memory contains zero personal action items
     (e.g. it's purely informational, content Dave is consuming, or
     someone else's commitment with no Dave follow-up).
   - "USER" means Dave is the owner. null means unclear. Named person means
     someone else owns it (still useful — ends up as waiting-for).
   - Be conservative: confidence 0.6 is the floor for inclusion. Below that,
     omit the item.
   - Verb-first task strings ("Email Karen the contract") not noun-form
     ("the contract for Karen").
   ```

3. **Per-memory call:** Haiku-class. ~$0.0001 per memory at current pricing. ~4k memories/week ≈ $0.40/week. Track cost in `extraction_metadata` for visibility.

4. **Quality monitoring:**
   - Every inserted `inbox_items` row gets `extraction_model = 'claude-haiku-4-5'` (or whichever).
   - Every triage decision sets `triage_outcome` (added in `efc_phase1c_extraction_columns` migration, already applied).
   - Weekly query: `SELECT * FROM efc.v_extractor_precision_weekly WHERE week >= now() - interval '4 weeks';`
   - **Escalation rule:** if Haiku precision < 0.70 for two consecutive full weeks, switch the poller to Sonnet for new extractions and re-evaluate. Keep both extractor labels in the data so the comparison is clean.

## Once extraction is producing reliably

1. Backfill: run the extractor over the existing 188k memories that have NULL action_items, in batches of ~500 with progress reporting.
2. Enable the systemd timer:
   ```bash
   ssh ralph 'sudo systemctl enable --now efc-poller.timer; \
              systemctl list-timers efc-poller.timer'
   ```
3. Verify by waiting ~10 minutes and checking:
   ```sql
   SELECT count(*) FROM efc.inbox_items WHERE source='openbrain' AND status='pending';
   ```
4. Mark the inbox items #2 (diagnose openbrain extraction) and #3 (enable poller timer) as done.

## Time budget

- **Diagnostics (queries 1–4):** 15 min.
- **If pipeline is fixable:** 30–60 min.
- **If pipeline is gone, fall-back extractor:** 60–90 min.

If at the 90-minute mark the system isn't auto-extracting, **stop and reassess** — don't sink the whole peak window.

## Done definition for Phase 1.C

- [ ] OpenBrain memories created in the last 24 hours have `action_items` populated, or the EFC poller's fallback extractor is producing them.
- [ ] `efc.inbox_items.extraction_model` is set on every auto-extracted row.
- [ ] `efc.poller_state` shows successful runs every ~5 minutes.
- [ ] At least one new inbox item from a real OpenBrain memory has flowed through `/triage` end-to-end.
- [ ] The `v_extractor_precision_weekly` view has rows.
