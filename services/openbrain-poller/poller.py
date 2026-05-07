#!/usr/bin/env python3
"""
EFC OpenBrain Poller
====================

Reads new memories from openbrain.memories, copies pre-extracted action
items into efc.inbox_items as 'pending' items for Dave to triage in his
morning briefing.

Owner-filter:
  - owner = 'USER'  → Dave's own to-do          → keep
  - owner is NULL   → ambiguous, conservative   → keep
  - owner = <name>  → someone else              → skip

Idempotent: dedupes by (openbrain_memory_id, extracted_action_item).

Runs as systemd oneshot every 5 minutes via efc-poller.timer.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

from supabase import create_client, Client


SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SOURCE = "openbrain"
BATCH_LIMIT = 200            # memories per run
MAX_INSERTED_LOG = 20        # how many ids to log on success


def log(msg: str) -> None:
    print(f"[efc-poller] {datetime.now(timezone.utc).isoformat()} {msg}", flush=True)


def get_last_polled(sb: Client) -> str | None:
    res = (
        sb.schema("efc")
        .table("poller_state")
        .select("last_polled_at")
        .eq("source", SOURCE)
        .execute()
    )
    if res.data:
        return res.data[0]["last_polled_at"]
    # First run — initialize the row, return None to mean "fetch all of last hour"
    init = datetime.now(timezone.utc).isoformat()
    sb.schema("efc").table("poller_state").insert(
        {"source": SOURCE, "last_polled_at": None, "last_run_status": "init"}
    ).execute()
    log("poller_state initialized")
    return None


def fetch_new_memories(sb: Client, since: str | None) -> list[dict]:
    """Memories created since last poll, with action_items populated, not archived."""
    q = (
        sb.schema("openbrain")
        .table("memories")
        .select(
            "id, content, memory_type, source, action_items, "
            "people, topics, created_at, original_timestamp, thread_id"
        )
        .neq("action_items", None)
        .eq("is_archived", False)
        .order("created_at", desc=False)
        .limit(BATCH_LIMIT)
    )
    if since:
        q = q.gt("created_at", since)
    return q.execute().data or []


def is_dave_task(action: dict) -> bool:
    owner = (action.get("owner") or "").strip().upper()
    if owner in ("", "USER", "DAVE", "DAVE LAYFIELD"):
        return True
    return False


def already_in_inbox(sb: Client, memory_id: str, task_text: str) -> bool:
    res = (
        sb.schema("efc")
        .table("inbox_items")
        .select("id")
        .eq("openbrain_memory_id", memory_id)
        .eq("extracted_action_item", task_text)
        .limit(1)
        .execute()
    )
    return bool(res.data)


def insert_inbox_item(
    sb: Client, memory: dict, action: dict
) -> str | None:
    task = (action.get("task") or "").strip()
    if not task:
        return None
    if already_in_inbox(sb, memory["id"], task):
        return None

    raw_text = memory.get("content") or task
    # Truncate raw_text — full memories can be huge
    if len(raw_text) > 4000:
        raw_text = raw_text[:4000] + "\n...[truncated]"

    payload = {
        "raw_text": raw_text,
        "extracted_action_item": task,
        "source": SOURCE,
        "openbrain_memory_id": memory["id"],
        "source_metadata": {
            "memory_type": memory.get("memory_type"),
            "memory_source": memory.get("source"),
            "people": memory.get("people"),
            "topics": memory.get("topics"),
            "thread_id": memory.get("thread_id"),
            "due": action.get("due"),
            "owner": action.get("owner"),
            "original_timestamp": memory.get("original_timestamp"),
        },
    }
    res = sb.schema("efc").table("inbox_items").insert(payload).execute()
    if res.data:
        return res.data[0]["id"]
    return None


def update_poller_state(sb: Client, latest_seen: str, status: str, notes: str) -> None:
    sb.schema("efc").table("poller_state").update(
        {
            "last_polled_at": latest_seen,
            "last_run_status": status,
            "last_run_notes": notes,
        }
    ).eq("source", SOURCE).execute()


def run() -> int:
    started = time.monotonic()
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    last_polled = get_last_polled(sb)
    log(f"last_polled_at={last_polled}")

    memories = fetch_new_memories(sb, last_polled)
    log(f"fetched {len(memories)} memories with action_items")

    inserted_ids: list[str] = []
    skipped_owner = 0
    skipped_dupe = 0
    latest_seen = last_polled

    for mem in memories:
        latest_seen = mem["created_at"]
        actions = mem.get("action_items") or []
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            if not is_dave_task(action):
                skipped_owner += 1
                continue
            inbox_id = insert_inbox_item(sb, mem, action)
            if inbox_id:
                inserted_ids.append(inbox_id)
            else:
                skipped_dupe += 1

    notes = json.dumps(
        {
            "memories_seen": len(memories),
            "inserted": len(inserted_ids),
            "skipped_owner": skipped_owner,
            "skipped_dupe_or_empty": skipped_dupe,
            "duration_s": round(time.monotonic() - started, 2),
        }
    )
    update_poller_state(
        sb,
        latest_seen or datetime.now(timezone.utc).isoformat(),
        "ok",
        notes,
    )
    log(f"done {notes}")
    if inserted_ids:
        log(f"inserted ids: {inserted_ids[:MAX_INSERTED_LOG]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as e:
        log(f"ERROR {type(e).__name__}: {e}")
        # Best-effort: record error in poller_state
        try:
            sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            sb.schema("efc").table("poller_state").update(
                {"last_run_status": "error", "last_run_notes": f"{type(e).__name__}: {e}"}
            ).eq("source", SOURCE).execute()
        except Exception:
            pass
        sys.exit(1)
