# EFC OpenBrain Poller

A small systemd-driven Python service that runs every 5 minutes on Ralph and copies pre-extracted action items from `openbrain.memories` into `efc.inbox_items` for triage.

## What it does

OpenBrain already extracts `action_items` from every memory it ingests (Gmail, Fireflies calls, ChatGPT/Claude history, GChat, YouTube, Mission Control briefings, etc.). The poller's only job is to forward Dave's items into the EFC inbox so they show up in `/inbox`, `/triage`, and `/briefing`.

**Owner filter:**
- `owner = "USER"` → Dave's task → forward
- `owner` null → ambiguous → forward (conservative; can prune at triage)
- `owner` is a named person → skip (someone else's commitment, not Dave's)

**Idempotent:** dedupes on `(openbrain_memory_id, extracted_action_item)`. Re-runs are safe.

## Files

| File | Purpose |
|---|---|
| `poller.py` | Main script. ~150 lines. Reads `efc.poller_state`, queries new memories, inserts inbox items, updates state. |
| `requirements.txt` | `supabase-py`. |
| `efc-poller.service` | systemd oneshot unit. |
| `efc-poller.timer` | Fires every 5 minutes. |
| `deploy-to-ralph.sh` | One-shot install: copies files, builds venv, writes `/etc/efc/env`, enables timer. |

## Deploy

From this directory on a machine with SSH access to Ralph:

```bash
export SUPABASE_URL="https://psmkklhyfkivyokhaiga.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="<service role key>"  # from clawd-context project

bash deploy-to-ralph.sh
```

The script:
1. Creates `/home/ubuntu/efc/openbrain-poller/` on Ralph.
2. Copies `poller.py` + installs deps in a venv.
3. Writes `/etc/efc/env` (mode 600) with the Supabase creds.
4. Installs `efc-poller.service` + `efc-poller.timer` to `/etc/systemd/system/`.
5. Enables the timer and runs the service once as a smoke test.
6. Tails the journal so you see the first run.

## Operate

```bash
# Tail logs in real time
ssh ralph 'journalctl -u efc-poller.service -f'

# When did it last run, when does it run next?
ssh ralph 'systemctl list-timers efc-poller.timer'

# Force a run right now
ssh ralph 'sudo systemctl start efc-poller.service'

# Status of the poller's own state row
psql "$SUPABASE_URL" -c "SELECT * FROM efc.poller_state WHERE source='openbrain';"
# (or run via the Supabase MCP from any Claude Code session)
```

## Tuning

- **Frequency:** edit `OnUnitActiveSec` in `efc-poller.timer`. Default 5 minutes. Hourly overnight is not implemented as a separate timer because empty runs are cheap (~1 second, one DB query).
- **Owner filter:** if too many items are getting through that aren't Dave's, tighten in `poller.py::is_dave_task()`.
- **Memory types:** the poller currently accepts any memory_type that has `action_items` populated. If specific types should be excluded (YouTube transcripts that occasionally generate spurious actions), filter at the SQL `select` step.

## Failure modes

- **Run errors** are logged to journald AND written to `efc.poller_state.last_run_status='error'` with the exception text in `last_run_notes`. So `/briefing` can surface "your poller has been failing for 3 hours" without you having to check logs.
- **Network blip** → next run picks up where this one stopped (idempotent; `last_polled_at` only advances on success).
- **Supabase outage** → service exits 1, timer keeps trying every 5 minutes.

## Off-switch

```bash
ssh ralph 'sudo systemctl disable --now efc-poller.timer'
```
