#!/usr/bin/env python3
"""
backfill_email_bodies.py — Catch up openbrain.email_bodies for historical
gmail threads that were ingested before format=full was wired into the
live ingester (Phase 1.D part 2, deployed 2026-05-07).

Strategy:
  1. For each Gmail OAuth account, call openbrain.list_missing_email_body_threads()
     to get the thread_ids that have a raw_entry but no email_bodies row.
  2. For each missing thread, fetch with format=full and call
     write_email_body() for each message in the thread.
  3. Throttle to ~5 req/sec per account (well under Gmail's 250/sec/user budget).
  4. Resumable: re-running picks up wherever the last run stopped because
     email_bodies upserts are idempotent and the function re-computes
     "missing" each invocation.
  5. Logs progress every PROGRESS_EVERY threads.

Run:
  /home/ubuntu/openbrain/connectors/gmail/backfill_email_bodies.py
or via systemd one-shot (see efc-backfill-email-bodies.service).
"""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Reuse the live ingester's helpers — same auth, same write_email_body, etc.
sys.path.insert(0, "/home/ubuntu/openbrain/connectors/gmail")
from openbrain_gmail_ingest import (  # noqa: E402
    GoogleAuth,
    get_thread,
    write_email_body,
    SUPABASE_URL,
    SUPABASE_PGRST_AUTH,
    EXCLUDED_ACCOUNTS,
    log,
)

THROTTLE_SECONDS = 0.2          # 5 requests / second
PROGRESS_EVERY = 100            # log every N threads per account
ACCOUNTS = [
    "dave@greenstreethousing.com",
    "dave@housr.ai",
    "dave@apartmentsmart.com",
    "dave@urbanorigin.io",
    "dflayfield@gmail.com",
]


def list_missing_threads(account: str) -> list[str]:
    """Call openbrain.list_missing_email_body_threads(account) via PostgREST RPC.

    The function returns text[] (single array), which PostgREST emits as a
    raw JSON array of strings. Arrays aren't subject to PostgREST's
    db-max-rows row cap (which capped the previous TABLE-returning version
    at 1000 entries even when there were 50k+ to deliver).
    """
    url = f"{SUPABASE_URL}/rest/v1/rpc/list_missing_email_body_threads"
    body = json.dumps({"p_account": account}).encode()
    req = Request(
        url,
        method="POST",
        headers={
            "apikey": SUPABASE_PGRST_AUTH,
            "Authorization": f"Bearer {SUPABASE_PGRST_AUTH}",
            "Content-Type": "application/json",
            "Content-Profile": "openbrain",
            "Accept-Profile": "openbrain",
        },
        data=body,
    )
    with urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read().decode())
    # PostgREST returns text[] as a raw JSON array of strings.
    if not isinstance(result, list):
        return []
    return [t for t in result if t]


def backfill_account(account: str) -> dict:
    if account in EXCLUDED_ACCOUNTS:
        log.info("[backfill] %s: excluded, skipping", account)
        return {"skipped": True}

    log.info("[backfill] %s: listing missing threads…", account)
    missing = list_missing_threads(account)
    total = len(missing)
    log.info("[backfill] %s: %d missing threads", account, total)
    if not total:
        return {"account": account, "total": 0, "fetched": 0, "errors": 0}

    auth = GoogleAuth(account)
    fetched = 0
    errors = 0
    started = time.monotonic()

    for i, tid in enumerate(missing, 1):
        try:
            thread = get_thread(auth, tid)
            for msg in (thread.get("messages") or []):
                write_email_body(account, msg)
            fetched += 1
        except Exception as e:
            errors += 1
            log.warning("[backfill] %s: thread %s failed: %s", account, tid, e)

        if i % PROGRESS_EVERY == 0:
            elapsed = time.monotonic() - started
            rate = i / elapsed if elapsed else 0.0
            remaining = (total - i) / rate if rate else 0.0
            log.info(
                "[backfill] %s: %d/%d (%.1f%%, %.1f/sec, ~%.0f min remaining)",
                account, i, total, 100.0 * i / total, rate, remaining / 60,
            )

        time.sleep(THROTTLE_SECONDS)

    log.info(
        "[backfill] %s: DONE — fetched=%d errors=%d in %.1f min",
        account, fetched, errors, (time.monotonic() - started) / 60,
    )
    return {"account": account, "total": total, "fetched": fetched, "errors": errors}


def main() -> int:
    log.info("=== backfill_email_bodies starting ===")
    started = time.monotonic()
    summary: list[dict] = []
    for account in ACCOUNTS:
        try:
            summary.append(backfill_account(account))
        except Exception as e:
            log.error("[backfill] %s: account-level failure: %s", account, e)
            summary.append({"account": account, "error": str(e)})

    elapsed_min = (time.monotonic() - started) / 60
    log.info("=== backfill_email_bodies complete in %.1f min ===", elapsed_min)
    log.info("Summary: %s", json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
