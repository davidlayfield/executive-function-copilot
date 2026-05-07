# OpenBrain Gmail Ingester (REFERENCE COPY)
# This is a snapshot of the production ingester running on Ralph at:
#   /home/ubuntu/openbrain/connectors/gmail/openbrain_gmail_ingest.py
# Deployed: 2026-05-07T23:41:19Z by Phase 1.D part 2.
# This file is a reference only — modifying it here does NOT change production.

#!/usr/bin/env python3
"""OpenBrain Gmail Ingester — direct Gmail API → ingest-memory edge function.

Bypasses Mission Control entirely. Reads OAuth tokens directly from
~/.clawdbot/credentials/google/<email>/{token.json,oauth_client.json},
refreshes access tokens on demand, and pulls new threads via Gmail's
incremental history API (fallback to date-bounded messages.list).

Designed to run hourly on the hour via systemd timer (Persistent=true).

Usage:
  python3 openbrain_gmail_ingest.py                    # incremental, all accounts
  python3 openbrain_gmail_ingest.py --account dave@housr.ai
  python3 openbrain_gmail_ingest.py --since 2026-03-19  # one-time backfill
  python3 openbrain_gmail_ingest.py --dry-run           # show what would ingest
"""

from __future__ import annotations

import argparse
import email as email_pkg
import imaplib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Gmail "All Mail" can have hundreds of thousands of UIDs in one SEARCH response;
# imaplib's default 1MB line cap is way too small.
imaplib._MAXLINE = 100_000_000

# ─── Config ──────────────────────────────────────────────────────────────────

CRED_BASE = Path.home() / ".clawdbot" / "credentials" / "google"
STATE_FILE = Path.home() / "openbrain" / "connectors" / ".gmail-sync-state-v2.json"
ENV_FILE = Path.home() / "openbrain" / ".env"
SUPABASE_URL = "https://psmkklhyfkivyokhaiga.supabase.co"
INGEST_ENDPOINT = f"{SUPABASE_URL}/functions/v1/ingest-memory"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Accounts excluded from OpenBrain (still syncs in MC, just not into memory).
EXCLUDED_ACCOUNTS: set[str] = {
    "info@apartmentsmart.com",  # shared company inbox — too noisy for personal memory
}

# How many threads to fetch per Gmail messages.list page.
GMAIL_PAGE_SIZE = 100
# Cap per-account work in a single hourly run (safety net).
MAX_THREADS_PER_RUN = 2000

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("openbrain-gmail")
sys.stdout.reconfigure(line_buffering=True)

# ─── Env ─────────────────────────────────────────────────────────────────────

def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    # Process env wins.
    for k in ("SUPABASE_SERVICE_ROLE_KEY", "OPENBRAIN_ACCESS_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env

ENV = load_env()
INGEST_AUTH = ENV.get("OPENBRAIN_ACCESS_KEY") or ENV.get("SUPABASE_SERVICE_ROLE_KEY")
if not INGEST_AUTH:
    log.error("No SUPABASE_SERVICE_ROLE_KEY or OPENBRAIN_ACCESS_KEY in env")
    sys.exit(2)

# ─── HTTP helpers ────────────────────────────────────────────────────────────

def http_json(url: str, *, method: str = "GET", headers: dict | None = None,
              body: bytes | None = None, timeout: int = 30) -> tuple[int, dict | str]:
    req = Request(url, method=method, headers=headers or {}, data=body)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return e.code, str(e)

# ─── OAuth ───────────────────────────────────────────────────────────────────

class GoogleAuth:
    """Per-account OAuth manager. Refreshes access tokens as needed; persists
    refreshed tokens back to disk so the next run sees a fresh access_token."""

    def __init__(self, email: str):
        self.email = email
        self.dir = CRED_BASE / email
        self.token_path = self.dir / "token.json"
        self.client_path = self.dir / "oauth_client.json"
        if not self.token_path.exists():
            raise FileNotFoundError(f"No token.json for {email}")
        if not self.client_path.exists():
            raise FileNotFoundError(f"No oauth_client.json for {email}")
        self._load()

    def _load(self) -> None:
        self._token_doc = json.loads(self.token_path.read_text())
        client_doc = json.loads(self.client_path.read_text())
        self._client = client_doc.get("installed") or client_doc.get("web") or client_doc

    @property
    def _tokens(self) -> dict:
        return self._token_doc.get("tokens") or self._token_doc

    def _save(self) -> None:
        self.token_path.write_text(json.dumps(self._token_doc, indent=2))

    def _expired(self) -> bool:
        exp = self._tokens.get("expiry_date") or 0
        # expiry_date is ms epoch in google-auth-library; treat <60s remaining as expired.
        return (exp / 1000.0) - time.time() < 60

    def _refresh(self) -> None:
        rt = self._tokens.get("refresh_token")
        if not rt:
            raise RuntimeError(f"{self.email}: no refresh_token in token.json")
        body = urlencode({
            "client_id": self._client["client_id"],
            "client_secret": self._client["client_secret"],
            "refresh_token": rt,
            "grant_type": "refresh_token",
        }).encode()
        status, payload = http_json(
            OAUTH_TOKEN_URL,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body,
        )
        if status != 200 or not isinstance(payload, dict) or "access_token" not in payload:
            raise RuntimeError(f"{self.email}: refresh failed {status} {payload}")
        # Update token doc in place.
        tk = self._tokens
        tk["access_token"] = payload["access_token"]
        tk["scope"] = payload.get("scope", tk.get("scope"))
        tk["token_type"] = payload.get("token_type", tk.get("token_type", "Bearer"))
        tk["expiry_date"] = int((time.time() + int(payload.get("expires_in", 3600))) * 1000)
        # If Google returned a rotated refresh token, keep it.
        if payload.get("refresh_token"):
            tk["refresh_token"] = payload["refresh_token"]
        self._token_doc["obtainedAt"] = int(time.time() * 1000)
        if "tokens" in self._token_doc:
            self._token_doc["tokens"] = tk
        else:
            # Flat shape — write back at top level too.
            for k, v in tk.items():
                self._token_doc[k] = v
        self._save()
        log.info("[%s] refreshed access token", self.email)

    def access_token(self) -> str:
        if self._expired():
            self._refresh()
        return self._tokens["access_token"]

    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token()}"}

# ─── State ───────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}

def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))

# ─── Gmail API ───────────────────────────────────────────────────────────────

def gmail_get(auth: GoogleAuth, path: str, params: dict | None = None) -> dict:
    url = f"{GMAIL_BASE}{path}"
    if params:
        # doseq=True so list values become repeated params (required by metadataHeaders).
        url += "?" + urlencode(params, doseq=True)
    status, payload = http_json(url, headers=auth.auth_header())
    if status == 401:
        auth._refresh()
        status, payload = http_json(url, headers=auth.auth_header())
    if status >= 400:
        raise RuntimeError(f"Gmail {path} → {status}: {payload}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Gmail {path} returned non-dict: {payload!r}")
    return payload

def get_profile(auth: GoogleAuth) -> dict:
    return gmail_get(auth, "/users/me/profile")

def list_thread_ids_since(auth: GoogleAuth, since_iso: str | None) -> list[str]:
    """Page through messages.list with q=after:<unix_ts>, return distinct thread IDs."""
    q = ""
    if since_iso:
        try:
            ts = int(datetime.fromisoformat(since_iso.replace("Z", "+00:00")).timestamp())
            q = f"after:{ts}"
        except Exception:
            log.warning("bad since_iso %s, ignoring", since_iso)
    thread_ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"maxResults": GMAIL_PAGE_SIZE}
        if q:
            params["q"] = q
        if page_token:
            params["pageToken"] = page_token
        payload = gmail_get(auth, "/users/me/messages", params)
        for msg in payload.get("messages", []) or []:
            tid = msg.get("threadId")
            if tid and tid not in seen:
                seen.add(tid)
                thread_ids.append(tid)
        page_token = payload.get("nextPageToken")
        if not page_token or len(thread_ids) >= MAX_THREADS_PER_RUN:
            break
    return thread_ids

def list_thread_ids_via_history(auth: GoogleAuth, start_history_id: str) -> tuple[list[str], str | None]:
    """Use the incremental history API. Returns (thread_ids, latest_history_id).
    Raises HistoryExpired if Gmail returns 404 (start_history_id older than ~7d)."""
    thread_ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    latest = start_history_id
    while True:
        params: dict[str, Any] = {
            "startHistoryId": start_history_id,
            "historyTypes": "messageAdded",
            "maxResults": 500,
        }
        if page_token:
            params["pageToken"] = page_token
        url = f"{GMAIL_BASE}/users/me/history"
        if params:
            url += "?" + urlencode(params)
        status, payload = http_json(url, headers=auth.auth_header())
        if status == 401:
            auth._refresh()
            status, payload = http_json(url, headers=auth.auth_header())
        if status == 404:
            raise HistoryExpired(start_history_id)
        if status >= 400 or not isinstance(payload, dict):
            raise RuntimeError(f"history.list → {status}: {payload}")
        for h in payload.get("history", []) or []:
            for ma in h.get("messagesAdded", []) or []:
                tid = (ma.get("message") or {}).get("threadId")
                if tid and tid not in seen:
                    seen.add(tid)
                    thread_ids.append(tid)
        if payload.get("historyId"):
            latest = payload["historyId"]
        page_token = payload.get("nextPageToken")
        if not page_token or len(thread_ids) >= MAX_THREADS_PER_RUN:
            break
    return thread_ids, latest

class HistoryExpired(Exception):
    def __init__(self, hid: str):
        super().__init__(f"history {hid} expired (>7d)")
        self.history_id = hid

_METADATA_HEADERS = ["From", "To", "Cc", "Subject", "Date"]

def get_thread(auth: GoogleAuth, thread_id: str) -> dict:
    # format=full returns the full MIME payload (bodies + attachments)
    # in addition to all the metadata format used to provide. Existing
    # snippet/header code paths keep working; full bodies are now also
    # available for write_email_body() below.
    return gmail_get(auth, f"/users/me/threads/{thread_id}",
                     {"format": "full"})

def get_message_snippet(auth: GoogleAuth, message_id: str) -> dict:
    return gmail_get(auth, f"/users/me/messages/{message_id}",
                     {"format": "metadata", "metadataHeaders": _METADATA_HEADERS})

# ─── Memory packaging ────────────────────────────────────────────────────────

def header(msg: dict, name: str) -> str:
    headers = (msg.get("payload") or {}).get("headers") or []
    name_lower = name.lower()
    for h in headers:
        if (h.get("name") or "").lower() == name_lower:
            return h.get("value") or ""
    return ""

def parse_addrs(s: str) -> list[str]:
    if not s:
        return []
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return parts

def build_memory(account_email: str, thread: dict) -> dict | None:
    msgs = thread.get("messages") or []
    if not msgs:
        return None
    subject = header(msgs[0], "Subject") or "(no subject)"
    senders: list[str] = []
    snippets: list[str] = []
    earliest = latest = None
    for m in msgs:
        sender = header(m, "From")
        date = header(m, "Date")
        snippet = (m.get("snippet") or "").strip()
        if sender and sender not in senders:
            senders.append(sender)
        if snippet:
            snippets.append(f"  [{date[:25]}] {sender}: {snippet[:240]}")
        ts = m.get("internalDate")
        if ts:
            ts_int = int(ts)
            earliest = ts_int if earliest is None else min(earliest, ts_int)
            latest = ts_int if latest is None else max(latest, ts_int)

    last_iso = (
        datetime.fromtimestamp(latest / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")
        if latest else "?"
    )

    content = (
        f"Email Thread: {subject}\n"
        f"Account: {account_email}\n"
        f"Messages: {len(msgs)} | Last: {last_iso}\n\n"
        f"Participants: {', '.join(senders) or '(unknown)'}\n\n"
        "Message snippets:\n"
        + "\n".join(snippets[:10])
    )

    return {
        "content": content,
        "source": "gmail",
        "memory_type": "general",
        "people": senders[:8],
        "topics": ["email"],
        "metadata": {
            "thread_id": thread.get("id"),
            "account": account_email,
            "subject": subject,
            "message_count": len(msgs),
            "last_internal_date": latest,
            "earliest_internal_date": earliest,
        },
    }

import base64

def _decode_part(part: dict) -> str:
    """Decode a single Gmail message part's body. Returns '' on failure."""
    data = (part.get("body") or {}).get("data") or ""
    if not data:
        return ""
    try:
        # Gmail uses URL-safe base64 with padding sometimes stripped.
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
    except Exception:
        return ""

def _walk_payload(part: dict, plain: list[str], html: list[str], atts: list[dict]) -> None:
    """Walk MIME tree once. Append plain/html bodies and attachments."""
    mime = part.get("mimeType", "")
    filename = part.get("filename") or ""
    body_meta = part.get("body") or {}
    sub = part.get("parts") or []

    if filename and (body_meta.get("size") or 0) > 0:
        atts.append({
            "filename": filename,
            "mime_type": mime,
            "size": body_meta.get("size", 0),
        })
    elif mime == "text/plain":
        text = _decode_part(part)
        if text:
            plain.append(text)
    elif mime == "text/html":
        text = _decode_part(part)
        if text:
            html.append(text)

    for child in sub:
        _walk_payload(child, plain, html, atts)

def _extract_bodies(payload: dict) -> tuple[str, str, list[dict]]:
    """Return (body_plain, body_html, attachments)."""
    plain: list[str] = []
    html: list[str] = []
    atts: list[dict] = []
    _walk_payload(payload, plain, html, atts)
    return "\n\n".join(plain).strip(), "\n\n".join(html).strip(), atts

_ADDR_RX = re.compile(r'^\s*"?([^"<]+?)"?\s*<([^>]+)>\s*$')

def _parse_address(raw: str) -> tuple[str | None, str | None]:
    """'Name <email@x.com>' -> (name, lower email). Bare email -> (None, email)."""
    if not raw:
        return None, None
    raw = raw.strip()
    m = _ADDR_RX.match(raw)
    if m:
        return m.group(1).strip(), m.group(2).strip().lower()
    if "@" in raw:
        return None, raw.lower()
    return raw, None

def _extract_address_list(headers_dict: dict, name: str) -> list[str]:
    raw = headers_dict.get(name, "")
    if not raw:
        return []
    out: list[str] = []
    for chunk in raw.split(","):
        _, addr = _parse_address(chunk)
        if addr:
            out.append(addr)
    return out

def write_email_body(account: str, msg: dict) -> None:
    """Upsert full body + headers for one Gmail message into openbrain.email_bodies.
    Best-effort: never raises out of this function. Logs warnings on any path failure
    so a body-write problem can't break the existing memory ingest."""
    try:
        message_id = msg.get("id")
        if not message_id:
            return
        if not SUPABASE_PGRST_AUTH:
            return  # skip silently if the env wasn't set
        thread_id = msg.get("threadId")
        payload = msg.get("payload") or {}
        headers_list = payload.get("headers") or []
        h = {(item.get("name") or "").lower(): item.get("value", "") for item in headers_list}

        body_plain, body_html, attachments = _extract_bodies(payload)
        from_name, from_addr = _parse_address(h.get("from", ""))

        date_str = h.get("date") or ""
        date_received = None
        if date_str:
            try:
                date_received = parsedate_to_datetime(date_str).isoformat()
            except Exception:
                date_received = None
        if not date_received:
            ts = msg.get("internalDate")
            if ts:
                try:
                    date_received = datetime.fromtimestamp(
                        int(ts) / 1000, tz=timezone.utc).isoformat()
                except Exception:
                    pass

        record = {
            "account": account,
            "message_id": message_id,
            "thread_id": thread_id,
            "in_reply_to": h.get("in-reply-to") or None,
            "subject": h.get("subject") or None,
            "from_name": from_name,
            "from_address": from_addr,
            "to_addresses": _extract_address_list(h, "to"),
            "cc_addresses": _extract_address_list(h, "cc"),
            "bcc_addresses": _extract_address_list(h, "bcc"),
            "date_received": date_received,
            "body_plain": body_plain or None,
            "body_html": body_html or None,
            "body_size_bytes": len(body_plain) + len(body_html),
            "has_attachments": len(attachments) > 0,
            "attachment_summary": attachments,
            "list_unsubscribe": h.get("list-unsubscribe") or None,
            "list_unsubscribe_post": h.get("list-unsubscribe-post") or None,
        }

        url = (f"{SUPABASE_URL}/rest/v1/email_bodies"
               f"?on_conflict=account,message_id")
        body = json.dumps(record).encode()
        req_headers = {
            "apikey": SUPABASE_PGRST_AUTH,
            "Authorization": f"Bearer {SUPABASE_PGRST_AUTH}",
            "Content-Type": "application/json",
            "Content-Profile": "openbrain",         # tells PostgREST to use openbrain schema
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        status, resp = http_json(url, method="POST", headers=req_headers,
                                 body=body, timeout=30)
        if status not in (200, 201, 204):
            log.warning("[%s] email_body upsert msg=%s status=%s body=%s",
                        account, message_id, status, str(resp)[:200])
    except Exception as e:
        log.warning("[%s] email_body upsert exception msg=%s: %s",
                    account, msg.get("id"), e)

def ingest_memory(memory: dict) -> tuple[bool, str]:
    body = json.dumps(memory).encode()
    status, payload = http_json(
        INGEST_ENDPOINT,
        method="POST",
        headers={
            "Authorization": f"Bearer {INGEST_AUTH}",
            "Content-Type": "application/json",
        },
        body=body,
        timeout=45,
    )
    if status == 200:
        return True, ""
    if status == 409:
        return True, "duplicate"
    if isinstance(payload, dict):
        msg = payload.get("message") or json.dumps(payload)[:200]
    else:
        msg = str(payload)[:200]
    return False, f"{status}: {msg}"

# ─── Ingest runs (writes openbrain.ingest_runs via public RPCs) ─────────────

CONNECTOR_ID = "gmail"
INGEST_RUN_RPC_BASE = f"{SUPABASE_URL}/rest/v1/rpc"
# PostgREST needs the supabase service_role key, not OPENBRAIN_ACCESS_KEY.
SUPABASE_PGRST_AUTH = ENV.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _ingest_runs_post(rpc: str, payload: dict) -> dict | None:
    """POST to a public RPC via PostgREST."""
    if not SUPABASE_PGRST_AUTH:
        return None  # silently skip if service_role key not configured
    body = json.dumps(payload).encode()
    req = Request(
        f"{INGEST_RUN_RPC_BASE}/{rpc}",
        data=body,
        method="POST",
        headers={
            "apikey": SUPABASE_PGRST_AUTH,
            "Authorization": f"Bearer {SUPABASE_PGRST_AUTH}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        log.warning("ingest_runs RPC %s failed: %s %s", rpc, e.code, e.read()[:200])
        return None


def start_ingest_run(metadata: dict | None = None) -> str | None:
    """Returns the run id, or None if the registry write failed (non-fatal)."""
    res = _ingest_runs_post("start_ingest_run", {
        "p_connector_id": CONNECTOR_ID,
        "p_metadata": metadata or {},
    })
    if isinstance(res, str):
        return res
    if isinstance(res, dict) and "id" in res:
        return res["id"]
    return None


def end_ingest_run(run_id: str | None, status: str, summary: dict) -> None:
    if not run_id:
        return
    _ingest_runs_post("end_ingest_run", {
        "p_run_id": run_id,
        "p_status": status,
        "p_items_ingested": summary.get("threads_ingested", 0),
        "p_items_duplicate": summary.get("threads_duplicate", 0),
        "p_items_errored": summary.get("errors", 0),
        "p_error_summary": None if summary.get("errors", 0) == 0 else f"{summary.get('errors', 0)} errors",
        "p_per_account": summary.get("per_account") or None,
    })


# ─── Heartbeat ───────────────────────────────────────────────────────────────

def capture_heartbeat(summary: dict) -> None:
    """Write a heartbeat memory so the watchdog can detect ingestion outages."""
    content = (
        "OpenBrain Gmail Ingest — Heartbeat\n"
        f"Run at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        f"Accounts processed: {summary.get('accounts_processed', 0)}\n"
        f"Threads ingested: {summary.get('threads_ingested', 0)}\n"
        f"Threads skipped (duplicate): {summary.get('threads_duplicate', 0)}\n"
        f"Errors: {summary.get('errors', 0)}\n"
        f"Per-account: {json.dumps(summary.get('per_account', {}))}"
    )
    memory = {
        "content": content,
        "source": "openbrain-heartbeat",
        "memory_type": "fact",
        "people": [],
        "topics": ["openbrain", "ingestion-heartbeat", "gmail"],
        "metadata": {"summary": summary},
    }
    ok, err = ingest_memory(memory)
    if not ok:
        log.warning("heartbeat ingest failed: %s", err)

# ─── Per-account loop ────────────────────────────────────────────────────────

def discover_accounts() -> list[str]:
    """Return accounts that have either OAuth (token.json+oauth_client.json)
    or IMAP App Password credentials. Excludes accounts in EXCLUDED_ACCOUNTS."""
    if not CRED_BASE.exists():
        return []
    out: list[str] = []
    for p in sorted(CRED_BASE.iterdir()):
        if not p.is_dir():
            continue
        name = p.name
        if "@" not in name:
            continue
        if name in EXCLUDED_ACCOUNTS:
            continue
        has_oauth = (p / "token.json").exists() and (p / "oauth_client.json").exists()
        has_imap = (p / "imap_app_password").exists()
        if not (has_oauth or has_imap):
            continue
        out.append(name)
    return out


def account_transport(email: str) -> str:
    """Return 'imap' if the account uses IMAP App Password, else 'oauth'."""
    if (CRED_BASE / email / "imap_app_password").exists():
        return "imap"
    return "oauth"

def process_account(email: str, state: dict, *, since: str | None, dry_run: bool) -> dict:
    if account_transport(email) == "imap":
        return process_account_imap(email, state, since=since, dry_run=dry_run)
    return process_account_oauth(email, state, since=since, dry_run=dry_run)


def process_account_oauth(email: str, state: dict, *, since: str | None, dry_run: bool) -> dict:
    stats = {"ingested": 0, "duplicate": 0, "errors": 0}
    try:
        auth = GoogleAuth(email)
    except Exception as e:
        log.error("[%s] auth init failed: %s", email, e)
        stats["errors"] += 1
        return stats

    try:
        profile = get_profile(auth)
    except Exception as e:
        log.error("[%s] profile fetch failed: %s", email, e)
        stats["errors"] += 1
        return stats

    current_history_id = profile.get("historyId")
    acct_state = state.setdefault(email, {})
    last_history_id = acct_state.get("history_id")

    thread_ids: list[str] = []
    new_history_id: str | None = current_history_id

    if since:
        # One-shot backfill mode.
        log.info("[%s] backfill since %s", email, since)
        thread_ids = list_thread_ids_since(auth, since)
    elif last_history_id:
        try:
            ids, latest = list_thread_ids_via_history(auth, last_history_id)
            thread_ids = ids
            new_history_id = latest or current_history_id
            log.info("[%s] history.list yielded %d threads", email, len(ids))
        except HistoryExpired:
            log.warning("[%s] history expired, falling back to messages.list", email)
            fallback_since = acct_state.get("last_seen_iso") or _yesterday_iso()
            thread_ids = list_thread_ids_since(auth, fallback_since)
    else:
        # Cold start: bring in last 24 hours and seed history_id.
        log.info("[%s] no prior state, seeding from last 24h", email)
        thread_ids = list_thread_ids_since(auth, _yesterday_iso())

    if dry_run:
        log.info("[%s] DRY RUN: would process %d threads", email, len(thread_ids))
        return stats

    latest_internal: int | None = acct_state.get("last_internal_date")

    for tid in thread_ids:
        try:
            thread = get_thread(auth, tid)
        except Exception as e:
            log.warning("[%s] thread %s fetch failed: %s", email, tid, e)
            stats["errors"] += 1
            continue
        memory = build_memory(email, thread)
        if not memory:
            continue
        ok, err = ingest_memory(memory)
        if ok and err == "duplicate":
            stats["duplicate"] += 1
        elif ok:
            stats["ingested"] += 1
        else:
            stats["errors"] += 1
            log.warning("[%s] thread %s ingest failed: %s", email, tid, err)
            continue

        # Phase 1.D: also write each message's full body to openbrain.email_bodies.
        # Best-effort. Failures don't abort the loop or mark the thread as errored —
        # bodies are an enrichment for Phase 4 inbox-AI, not a hard dependency for OB.
        for msg in (thread.get("messages") or []):
            write_email_body(email, msg)

        ts = memory["metadata"].get("last_internal_date")
        if ts and (latest_internal is None or ts > latest_internal):
            latest_internal = ts

    # Update state.
    if new_history_id:
        acct_state["history_id"] = new_history_id
    if latest_internal:
        acct_state["last_internal_date"] = latest_internal
        acct_state["last_seen_iso"] = datetime.fromtimestamp(
            latest_internal / 1000, tz=timezone.utc
        ).isoformat(timespec="seconds")
    acct_state["last_run_iso"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    log.info("[%s] done: ingested=%d duplicate=%d errors=%d",
             email, stats["ingested"], stats["duplicate"], stats["errors"])
    return stats

def _yesterday_iso() -> str:
    return datetime.fromtimestamp(time.time() - 86400, tz=timezone.utc).isoformat()


# ─── IMAP transport (consumer Gmail accounts via App Password) ───────────────

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
IMAP_FOLDER = '"[Gmail]/All Mail"'
# IMAP fetches are per-message (not per-thread like the API); cap higher.
MAX_IMAP_MESSAGES_PER_RUN = 5000


def _imap_date(iso: str) -> str:
    """ISO date string -> IMAP DD-Mon-YYYY format."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.strftime("%d-%b-%Y")


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    out = []
    for chunk, charset in email_pkg.header.decode_header(value):
        if isinstance(chunk, bytes):
            try:
                out.append(chunk.decode(charset or "utf-8", "replace"))
            except LookupError:
                out.append(chunk.decode("utf-8", "replace"))
        else:
            out.append(chunk)
    return "".join(out).strip()


def _extract_snippet(msg, limit: int = 240) -> str:
    """Walk message parts, return first ~limit chars of text/plain (or stripped HTML)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and part.get_filename() is None:
                return _payload_to_text(part)[:limit]
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = _payload_to_text(part)
                return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))[:limit]
    else:
        return _payload_to_text(msg)[:limit]
    return ""


def _payload_to_text(part) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        text = payload.decode(charset, "replace")
    except LookupError:
        text = payload.decode("utf-8", "replace")
    return " ".join(text.split())


_XGM_THRID_RE = re.compile(rb"X-GM-THRID\s+(\d+)")

def _parse_xgm_thrid(chunk: bytes | None) -> str | None:
    if not chunk:
        return None
    m = _XGM_THRID_RE.search(chunk)
    return m.group(1).decode() if m else None


def _imap_status_uidvalidity(M: imaplib.IMAP4_SSL) -> str | None:
    typ, data = M.status(IMAP_FOLDER, "(UIDVALIDITY)")
    if typ != "OK" or not data or not data[0]:
        return None
    m = re.search(rb"UIDVALIDITY\s+(\d+)", data[0])
    return m.group(1).decode() if m else None


def _build_imap_memory(account: str, thrid: str, msgs: list[dict]) -> dict:
    msgs.sort(key=lambda m: m["internal_dt"])
    first = msgs[0]
    last = msgs[-1]
    senders = []
    for m in msgs:
        if m["sender"] and m["sender"] not in senders:
            senders.append(m["sender"])
    last_iso = last["internal_dt"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")
    snippets = "\n".join(
        f"  [{m['date'][:25]}] {m['sender']}: {m['snippet']}" for m in msgs[:10]
    )
    content = (
        f"Email Thread: {first['subject'] or '(no subject)'}\n"
        f"Account: {account}\n"
        f"Messages: {len(msgs)} | Last: {last_iso}\n\n"
        f"Participants: {', '.join(senders) or '(unknown)'}\n\n"
        "Message snippets:\n" + snippets
    )
    return {
        "content": content,
        "source": "gmail",
        "memory_type": "general",
        "people": senders[:8],
        "topics": ["email"],
        "metadata": {
            "thread_id": thrid,
            "account": account,
            "subject": first["subject"],
            "message_count": len(msgs),
            "last_internal_date": int(last["internal_dt"].timestamp() * 1000),
            "earliest_internal_date": int(first["internal_dt"].timestamp() * 1000),
            "ingest_path": "imap",
        },
    }


def process_account_imap(email: str, state: dict, *, since: str | None, dry_run: bool) -> dict:
    stats = {"ingested": 0, "duplicate": 0, "errors": 0}
    pw_path = CRED_BASE / email / "imap_app_password"
    try:
        pw = pw_path.read_text().strip()
    except Exception as e:
        log.error("[%s] cannot read IMAP password: %s", email, e)
        stats["errors"] += 1
        return stats

    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        typ, _ = M.login(email, pw)
        if typ != "OK":
            raise RuntimeError("IMAP login failed")
    except Exception as e:
        log.error("[%s] IMAP login failed: %s", email, e)
        stats["errors"] += 1
        return stats

    try:
        uidvalidity = _imap_status_uidvalidity(M)
        typ, sel_data = M.select(IMAP_FOLDER, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"IMAP select failed: {sel_data}")

        acct_state = state.setdefault(email, {})
        last_uid = acct_state.get("imap_last_uid")
        last_uidvalidity = acct_state.get("imap_uidvalidity")

        # Pick the search criteria.
        if since:
            search_args: tuple = ("SINCE", _imap_date(since))
            log.info("[%s] IMAP backfill since %s", email, since)
        elif last_uid and last_uidvalidity == uidvalidity:
            search_args = ("UID", f"{int(last_uid)+1}:*")
            log.info("[%s] IMAP incremental (UID > %s)", email, last_uid)
        else:
            search_args = ("SINCE", _imap_date(_yesterday_iso()))
            if last_uidvalidity and last_uidvalidity != uidvalidity:
                log.warning("[%s] UIDVALIDITY changed (%s → %s); falling back to SINCE",
                            email, last_uidvalidity, uidvalidity)
            else:
                log.info("[%s] IMAP cold start (last 24h)", email)

        typ, data = M.uid("SEARCH", *search_args)
        if typ != "OK":
            raise RuntimeError(f"IMAP search failed: {data}")
        uids = data[0].split() if data and data[0] else []
        log.info("[%s] IMAP found %d UIDs", email, len(uids))

        if dry_run:
            log.info("[%s] DRY RUN: would process %d messages", email, len(uids))
            return stats

        if len(uids) > MAX_IMAP_MESSAGES_PER_RUN:
            log.warning("[%s] capping at %d UIDs (was %d) — extra will catch up next run",
                        email, MAX_IMAP_MESSAGES_PER_RUN, len(uids))
            uids = uids[:MAX_IMAP_MESSAGES_PER_RUN]

        # Fetch each UID, group by X-GM-THRID.
        threads: dict[str, list[dict]] = {}
        max_uid_seen = int(last_uid) if last_uid else 0
        for uid in uids:
            try:
                typ, meta = M.uid("FETCH", uid, "(X-GM-THRID INTERNALDATE)")
                thrid = _parse_xgm_thrid(meta[0]) if meta and meta[0] else None
                typ, msg_data = M.uid("FETCH", uid, "(BODY.PEEK[])")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email_pkg.message_from_bytes(raw)
                date_hdr = _decode_header(msg.get("Date"))
                try:
                    internal_dt = parsedate_to_datetime(date_hdr)
                    if internal_dt.tzinfo is None:
                        internal_dt = internal_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    internal_dt = datetime.now(timezone.utc)
                threads.setdefault(thrid or uid.decode(), []).append({
                    "subject": _decode_header(msg.get("Subject")),
                    "sender": _decode_header(msg.get("From")),
                    "date": date_hdr,
                    "snippet": _extract_snippet(msg, 240),
                    "internal_dt": internal_dt,
                })
                u = int(uid.decode())
                if u > max_uid_seen:
                    max_uid_seen = u
            except Exception as e:
                log.warning("[%s] uid %s: %s", email, uid.decode() if isinstance(uid, bytes) else uid, e)
                stats["errors"] += 1

        log.info("[%s] grouped %d msgs into %d threads",
                 email, sum(len(v) for v in threads.values()), len(threads))

        latest_internal: int | None = acct_state.get("last_internal_date")
        for thrid, msgs in threads.items():
            mem = _build_imap_memory(email, thrid, msgs)
            ok, err = ingest_memory(mem)
            if ok and err == "duplicate":
                stats["duplicate"] += 1
            elif ok:
                stats["ingested"] += 1
            else:
                stats["errors"] += 1
                log.warning("[%s] thread %s ingest failed: %s", email, thrid, err)
                continue
            ts = mem["metadata"].get("last_internal_date")
            if ts and (latest_internal is None or ts > latest_internal):
                latest_internal = ts

        acct_state["imap_uidvalidity"] = uidvalidity
        if max_uid_seen > 0:
            acct_state["imap_last_uid"] = str(max_uid_seen)
        if latest_internal:
            acct_state["last_internal_date"] = latest_internal
            acct_state["last_seen_iso"] = datetime.fromtimestamp(
                latest_internal / 1000, tz=timezone.utc
            ).isoformat(timespec="seconds")
        acct_state["last_run_iso"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        acct_state["transport"] = "imap"

        log.info("[%s] IMAP done: ingested=%d duplicate=%d errors=%d",
                 email, stats["ingested"], stats["duplicate"], stats["errors"])
    finally:
        try:
            M.logout()
        except Exception:
            pass

    return stats

# ─── Main ────────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", action="append", help="restrict to specific email(s)")
    ap.add_argument("--since", help="ISO date for one-shot backfill (overrides history)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-heartbeat", action="store_true")
    args = ap.parse_args(argv)

    accounts = args.account or discover_accounts()
    if not accounts:
        log.error("no accounts found")
        return 2

    state = load_state()
    summary = {
        "accounts_processed": 0,
        "threads_ingested": 0,
        "threads_duplicate": 0,
        "errors": 0,
        "per_account": {},
    }
    started = time.time()

    # Register a run row in openbrain.ingest_runs (best effort; failures
    # don't block ingestion).
    run_id: str | None = None
    if not args.dry_run:
        run_id = start_ingest_run({
            "since": args.since,
            "accounts": accounts,
            "host": "ralph-systemd",
        })

    try:
        for email in accounts:
            log.info("=== %s ===", email)
            stats = process_account(email, state, since=args.since, dry_run=args.dry_run)
            summary["accounts_processed"] += 1
            summary["threads_ingested"] += stats["ingested"]
            summary["threads_duplicate"] += stats["duplicate"]
            summary["errors"] += stats["errors"]
            summary["per_account"][email] = stats
            if not args.dry_run:
                save_state(state)
    except Exception as e:
        if run_id:
            end_ingest_run(run_id, "failed", {**summary, "error_summary": str(e)[:500]})
        raise

    elapsed = time.time() - started
    log.info("=== run complete in %.1fs: %s ===", elapsed, summary)

    if run_id:
        # 'partial' if there were errors but at least one account succeeded;
        # 'succeeded' if zero errors; 'failed' if every account errored.
        if summary["errors"] == 0:
            run_status = "succeeded"
        elif summary["accounts_processed"] > 0 and summary["threads_ingested"] > 0:
            run_status = "partial"
        else:
            run_status = "failed"
        end_ingest_run(run_id, run_status, summary)

    if not args.dry_run and not args.no_heartbeat:
        capture_heartbeat(summary)

    return 0 if summary["errors"] == 0 else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
