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
of 600000 ms (the script stops itself after at most about 8.5 minutes):

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
- Takes up to `EXTRACT_BATCH` (default 10) rows that still need extraction, in
  priority order: `journal_entries`, `interactions`, `knowledge_atoms`, then
  `inbox_email_log` newest first.
- Email rows are fed WITH their body from `openbrain.email_bodies` (joined on
  `message_id`). An email row with no usable body is skipped and left unmarked,
  so it is picked up once its body lands. `noise` and `spam` are never fed.
- Runs every lens in one model call per row via `claude -p`, on the
  subscription token this run was given, never an API key.
- Claims the row (marks it processed) BEFORE writing its outputs, then writes
  mentions, candidates, relationships, open questions, behavior signals and lens
  candidates. A model error or a failed claim leaves the row unmarked with
  nothing written, so next hour's retry cannot duplicate anything. A failed
  insert after the claim is logged (status `partial`) and not retried, so a
  row's outputs are written at most once.
- No row starts after `EXTRACT_TIME_BUDGET` (420 s) and no model call runs past
  that plus `EXTRACT_GRACE` (90 s), so a run ends inside the 600 s Bash cap.
- `--dry-run` runs everything except the writes, for testing.
