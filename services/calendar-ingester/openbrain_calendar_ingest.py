#!/usr/bin/env python3
"""
Dave OS Calendar Ingester — sync Google Calendar events into efc.calendar_events.

Mirrors openbrain_gmail_ingest pattern:
  - reads OAuth tokens from ~/.clawdbot/credentials/google/<email>/
  - refreshes access tokens on demand
  - uses Calendar API events.list with sync token for incremental updates

Designed to run every 10 minutes via systemd timer.

Usage:
  python3 openbrain_calendar_ingest.py                    # incremental, all accounts
  python3 openbrain_calendar_ingest.py --account dave@housr.ai
  python3 openbrain_calendar_ingest.py --full             # full resync (drop sync token)
  python3 openbrain_calendar_ingest.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Reuse the auth machinery + helpers from the gmail ingester.
sys.path.insert(0, "/home/ubuntu/openbrain/connectors/gmail")
from openbrain_gmail_ingest import (  # noqa: E402
    GoogleAuth, gmail_get,            # gmail_get is generic enough — uses GMAIL_BASE though, can't reuse
    SUPABASE_URL, SUPABASE_PGRST_AUTH, http_json,
    EXCLUDED_ACCOUNTS, log,
)

CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
DEFAULT_CALENDAR_ID = "primary"
LOOK_BACK_DAYS = 7         # for first sync, pull last 7 days
LOOK_FORWARD_DAYS = 60     # ...and next 60 days


def cal_get(auth: GoogleAuth, path: str, params: dict | None = None) -> dict:
    """Generic Calendar API GET. Mirrors gmail_get but for calendar.googleapis.com."""
    url = f"{CALENDAR_BASE}{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers=auth.auth_header())
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"calendar API {path} HTTP {e.code}: {body}") from e


def get_sync_state(account: str) -> dict | None:
    """Pull current sync_token + last_synced_at for the account."""
    url = (f"{SUPABASE_URL}/rest/v1/calendar_sync_state"
           f"?account=eq.{account}&select=*")
    req = Request(url, headers={
        "apikey": SUPABASE_PGRST_AUTH,
        "Authorization": f"Bearer {SUPABASE_PGRST_AUTH}",
        "Accept-Profile": "efc",
    })
    with urlopen(req, timeout=30) as resp:
        rows = json.loads(resp.read().decode())
    return rows[0] if rows else None


def upsert_sync_state(account: str, **kwargs) -> None:
    payload = {"account": account, **kwargs, "updated_at": datetime.now(timezone.utc).isoformat()}
    url = f"{SUPABASE_URL}/rest/v1/calendar_sync_state?on_conflict=account"
    body = json.dumps(payload).encode()
    req = Request(url, method="POST", headers={
        "apikey": SUPABASE_PGRST_AUTH,
        "Authorization": f"Bearer {SUPABASE_PGRST_AUTH}",
        "Content-Type": "application/json",
        "Content-Profile": "efc",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }, data=body)
    try:
        with urlopen(req, timeout=30) as resp:
            resp.read()
    except HTTPError as e:
        log.warning("[%s] sync_state upsert failed %s: %s", account, e.code,
                    e.read().decode(errors='replace')[:300])


def list_events(auth: GoogleAuth, calendar_id: str, *,
                sync_token: str | None = None,
                time_min_iso: str | None = None,
                time_max_iso: str | None = None) -> tuple[list[dict], str | None, bool]:
    """Page through events.list. Returns (events, next_sync_token, sync_invalid)."""
    events: list[dict] = []
    page_token: str | None = None
    next_sync_token: str | None = None
    sync_invalid = False

    while True:
        params: dict[str, str] = {
            "maxResults": "250",
            "singleEvents": "true",
        }
        if sync_token:
            # Incremental sync
            params["syncToken"] = sync_token
        else:
            # Time-bounded full sync
            if time_min_iso:
                params["timeMin"] = time_min_iso
            if time_max_iso:
                params["timeMax"] = time_max_iso
            params["showDeleted"] = "true"   # Only allowed on full sync
        if page_token:
            params["pageToken"] = page_token

        try:
            data = cal_get(auth, f"/calendars/{calendar_id}/events", params)
        except RuntimeError as e:
            err_str = str(e)
            if "410" in err_str and sync_token:
                log.warning("Sync token expired (410). Will full-resync.")
                sync_invalid = True
                return events, None, True
            raise

        items = data.get("items") or []
        events.extend(items)
        page_token = data.get("nextPageToken")
        next_sync_token = data.get("nextSyncToken") or next_sync_token
        if not page_token:
            break

    return events, next_sync_token, sync_invalid


def parse_event(account: str, ev: dict, dave_email: str) -> dict | None:
    """Convert a Google Calendar event to a row for efc.calendar_events."""
    if ev.get("status") == "cancelled" and not ev.get("recurringEventId"):
        # Cancelled non-instance — return None to mark for delete (we'll handle in writer)
        return {"_delete_only": True, "google_event_id": ev.get("id"), "account": account}

    google_event_id = ev.get("id")
    if not google_event_id:
        return None

    # Time fields can be either dateTime+timeZone (with TZ) or date (all-day).
    start = ev.get("start") or {}
    end = ev.get("end") or {}
    is_all_day = bool(start.get("date"))
    start_at = None
    end_at = None
    start_date = None
    end_date = None
    timezone_str = start.get("timeZone")

    if is_all_day:
        start_date = start.get("date")
        end_date = end.get("date")
    else:
        start_at = start.get("dateTime")
        end_at = end.get("dateTime")

    duration_min = None
    if start_at and end_at:
        try:
            sdt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
            edt = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
            duration_min = int((edt - sdt).total_seconds() / 60)
        except Exception:
            duration_min = None

    creator = ev.get("creator") or {}
    organizer = ev.get("organizer") or {}
    is_dave_org = organizer.get("email", "").lower() == dave_email.lower()

    attendees_raw = ev.get("attendees") or []
    attendee_emails = [a.get("email", "").lower() for a in attendees_raw if a.get("email")]
    dave_resp = None
    for a in attendees_raw:
        if (a.get("email") or "").lower() == dave_email.lower():
            dave_resp = a.get("responseStatus")
            break

    conf = ev.get("conferenceData") or {}
    conf_link = None
    conf_kind = None
    for entry in (conf.get("entryPoints") or []):
        if entry.get("entryPointType") == "video":
            conf_link = entry.get("uri")
            break
    sol = (conf.get("conferenceSolution") or {}).get("name", "").lower()
    if "meet" in sol:
        conf_kind = "meet"
    elif "zoom" in sol:
        conf_kind = "zoom"
    elif "teams" in sol or "microsoft" in sol:
        conf_kind = "teams"
    elif conf_link:
        conf_kind = "other"

    rec = ev.get("recurrence") or []
    rec_str = "\n".join(rec) if rec else None

    return {
        "account": account,
        "google_event_id": google_event_id,
        "google_calendar_id": "primary",
        "ical_uid": ev.get("iCalUID"),
        "html_link": ev.get("htmlLink"),
        "recurring_event_id": ev.get("recurringEventId"),
        "recurrence_rrule": rec_str,
        "summary": ev.get("summary"),
        "description": ev.get("description"),
        "location": ev.get("location"),
        "creator_email": (creator.get("email") or "").lower() or None,
        "creator_name": creator.get("displayName"),
        "organizer_email": (organizer.get("email") or "").lower() or None,
        "organizer_name": organizer.get("displayName"),
        "start_at": start_at,
        "end_at": end_at,
        "start_date": start_date,
        "end_date": end_date,
        "is_all_day": is_all_day,
        "duration_minutes": duration_min,
        "timezone": timezone_str,
        "status": ev.get("status"),
        "visibility": ev.get("visibility"),
        "conference_link": conf_link,
        "conference_kind": conf_kind,
        "attendees": attendees_raw,
        "attendee_emails": attendee_emails,
        "num_attendees": len(attendee_emails),
        "dave_response": dave_resp,
        "is_dave_organizer": is_dave_org,
        "google_created_at": ev.get("created"),
        "google_updated_at": ev.get("updated"),
    }


def write_events(rows: list[dict]) -> int:
    """Bulk upsert into efc.calendar_events."""
    if not rows:
        return 0
    # Filter out any None or delete-only here; deletes handled separately
    inserts = [r for r in rows if r and not r.get("_delete_only")]
    deletes = [r for r in rows if r and r.get("_delete_only")]

    inserted = 0
    if inserts:
        url = (f"{SUPABASE_URL}/rest/v1/calendar_events"
               f"?on_conflict=account,google_event_id")
        body = json.dumps(inserts).encode()
        req = Request(url, method="POST", headers={
            "apikey": SUPABASE_PGRST_AUTH,
            "Authorization": f"Bearer {SUPABASE_PGRST_AUTH}",
            "Content-Type": "application/json",
            "Content-Profile": "efc",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }, data=body)
        try:
            with urlopen(req, timeout=60) as resp:
                resp.read()
            inserted = len(inserts)
        except HTTPError as e:
            log.warning("calendar_events upsert failed %s: %s", e.code,
                        e.read().decode(errors='replace')[:500])

    # Mark cancelled events as cancelled (not delete — keep history)
    for d in deletes:
        url = (f"{SUPABASE_URL}/rest/v1/calendar_events"
               f"?account=eq.{d['account']}&google_event_id=eq.{d['google_event_id']}")
        body = json.dumps({"status": "cancelled",
                          "updated_at": datetime.now(timezone.utc).isoformat()}).encode()
        req = Request(url, method="PATCH", headers={
            "apikey": SUPABASE_PGRST_AUTH,
            "Authorization": f"Bearer {SUPABASE_PGRST_AUTH}",
            "Content-Type": "application/json",
            "Content-Profile": "efc",
            "Prefer": "return=minimal",
        }, data=body)
        try:
            with urlopen(req, timeout=15) as resp:
                resp.read()
        except Exception as e:
            log.debug("cancel mark failed for %s/%s: %s", d['account'], d['google_event_id'], e)

    return inserted


def discover_accounts() -> list[str]:
    base = Path.home() / ".clawdbot" / "credentials" / "google"
    if not base.exists():
        return []
    accounts = []
    for child in base.iterdir():
        if child.is_dir() and (child / "token.json").exists():
            email = child.name
            if email not in EXCLUDED_ACCOUNTS:
                accounts.append(email)
    return accounts


def process_account(account: str, *, full_resync: bool = False, dry_run: bool = False) -> dict:
    log.info("=== %s ===", account)
    auth = GoogleAuth(account)

    state = get_sync_state(account)
    sync_token = None if full_resync else (state or {}).get("sync_token")

    time_min_iso = None
    time_max_iso = None
    if not sync_token:
        # Full sync window
        now = datetime.now(timezone.utc)
        time_min_iso = (now - timedelta(days=LOOK_BACK_DAYS)).isoformat()
        time_max_iso = (now + timedelta(days=LOOK_FORWARD_DAYS)).isoformat()
        log.info("[%s] full sync window: %s → %s", account, time_min_iso, time_max_iso)
    else:
        log.info("[%s] incremental sync with token", account)

    try:
        events, next_token, sync_invalid = list_events(
            auth, DEFAULT_CALENDAR_ID,
            sync_token=sync_token,
            time_min_iso=time_min_iso,
            time_max_iso=time_max_iso,
        )
    except RuntimeError as e:
        log.error("[%s] failed: %s", account, e)
        upsert_sync_state(account, last_synced_at=datetime.now(timezone.utc).isoformat(),
                         last_sync_status="error", last_sync_notes=str(e)[:500])
        return {"account": account, "error": str(e)}

    if sync_invalid:
        # Recurse with full_resync
        log.info("[%s] sync token invalid, doing full resync", account)
        return process_account(account, full_resync=True, dry_run=dry_run)

    log.info("[%s] fetched %d events", account, len(events))

    if dry_run:
        return {"account": account, "fetched": len(events), "dry_run": True}

    rows = [parse_event(account, ev, account) for ev in events]
    inserted = write_events(rows)

    upsert_sync_state(account,
                     sync_token=next_token,
                     last_synced_at=datetime.now(timezone.utc).isoformat(),
                     last_sync_status="ok",
                     last_sync_notes=f"events={len(events)} inserted={inserted}")
    log.info("[%s] done: events=%d inserted=%d", account, len(events), inserted)
    return {"account": account, "fetched": len(events), "inserted": inserted}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account")
    parser.add_argument("--full", action="store_true", help="Force full resync")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    started = time.monotonic()
    accounts = [args.account] if args.account else discover_accounts()
    if not accounts:
        log.error("No accounts found in ~/.clawdbot/credentials/google/")
        return 2

    summary = []
    for acct in accounts:
        try:
            summary.append(process_account(acct, full_resync=args.full, dry_run=args.dry_run))
        except Exception as e:
            log.error("[%s] uncaught: %s", acct, e)
            summary.append({"account": acct, "error": str(e)})

    elapsed = time.monotonic() - started
    log.info("=== run complete in %.1fs: %s ===", elapsed, json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
