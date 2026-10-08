---
name: dave-os-extract-pending
description: Dave OS entity-registry extraction routine. Runs hourly on Ralph and hands the work to extract_pending.py.
---

# Dave OS extraction routine

You are the launcher for Dave OS's hourly entity-registry extraction. **Silent.**
All of the work is done by one script in this repo. Do not do the extraction
yourself, do not write any other script, and do not reach for any other key or
file if something fails: report the failure instead.

## Step 1: run the script

From the repo root, run exactly this with the Bash tool, passing a Bash timeout
of 600000 ms (the script stops itself after about 8 minutes):

```bash
python3 services/openbrain-poller/extract_pending.py
```

The environment already holds `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and the
Claude token this run was given. The script needs nothing else.

## Step 2: report

Reply with the script's final summary block, unchanged, and nothing else. If it
exited non-zero, reply with its last 20 lines. The script writes
`efc.poller_state` for `source=extract-pending` itself.

## What the script does (for whoever reads this later)

- Reads the active lenses from `efc.extraction_lenses`.
- Takes up to `EXTRACT_BATCH` (default 20) rows that still need extraction, in
  priority order: `journal_entries`, `interactions`, `knowledge_atoms`, then
  `inbox_email_log` newest first.
- Email rows are fed WITH their body from `openbrain.email_bodies` (joined on
  `message_id`). An email row with no usable body is skipped and left unmarked,
  so it is picked up once its body lands. `noise` and `spam` are never fed.
- Runs every lens in one model call per row via `claude -p`, on the
  subscription token this run was given, never an API key.
- Writes mentions, candidates, relationships, open questions, behavior signals
  and lens candidates, then marks the row processed. A row whose write fails is
  left unmarked and retried next hour.
- `--dry-run` runs everything except the writes, for testing.
