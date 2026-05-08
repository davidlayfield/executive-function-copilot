#!/usr/bin/env python3
"""
Gmail archive helper — removes the INBOX label from a thread (archives it).
Reuses the existing GoogleAuth class for OAuth token handling.

Usage:
  python3 gmail_archive.py <account> <thread_id>          # archive whole thread
  python3 gmail_archive.py <account> --message <msg_id>   # archive one message
  python3 gmail_archive.py <account> <thread_id> --read   # also mark as read

Requires the account's token.json to have scope gmail.modify.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# Reuse the gmail ingester's auth machinery
sys.path.insert(0, "/home/ubuntu/openbrain/connectors/gmail")
from openbrain_gmail_ingest import GoogleAuth, GMAIL_BASE  # noqa: E402


def archive_thread(auth: GoogleAuth, thread_id: str, mark_read: bool = False) -> dict:
    """Archive a Gmail thread by removing INBOX label. Optionally mark as read."""
    remove = ["INBOX"]
    if mark_read:
        remove.append("UNREAD")
    url = f"{GMAIL_BASE}/users/me/threads/{thread_id}/modify"
    body = json.dumps({"removeLabelIds": remove}).encode()
    headers = {**auth.auth_header(), "Content-Type": "application/json"}
    req = Request(url, method="POST", headers=headers, data=body)
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def archive_message(auth: GoogleAuth, message_id: str, mark_read: bool = False) -> dict:
    remove = ["INBOX"]
    if mark_read:
        remove.append("UNREAD")
    url = f"{GMAIL_BASE}/users/me/messages/{message_id}/modify"
    body = json.dumps({"removeLabelIds": remove}).encode()
    headers = {**auth.auth_header(), "Content-Type": "application/json"}
    req = Request(url, method="POST", headers=headers, data=body)
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("account", help="Email account, e.g. dave@greenstreethousing.com")
    parser.add_argument("target", nargs="?", help="thread_id (default) or message_id with --message")
    parser.add_argument("--message", action="store_true", help="Archive single message instead of whole thread")
    parser.add_argument("--read", action="store_true", help="Also mark as read")
    args = parser.parse_args()

    if not args.target:
        print("ERROR: target (thread_id or message_id) required")
        return 1

    try:
        auth = GoogleAuth(args.account)
    except Exception as e:
        print(f"ERROR: cannot load auth for {args.account}: {e}")
        return 2

    try:
        if args.message:
            result = archive_message(auth, args.target, mark_read=args.read)
            print(json.dumps({
                "ok": True, "kind": "message",
                "id": result.get("id"),
                "labels": result.get("labelIds", []),
            }))
        else:
            result = archive_thread(auth, args.target, mark_read=args.read)
            print(json.dumps({
                "ok": True, "kind": "thread",
                "id": result.get("id"),
                "messages": len(result.get("messages") or []),
            }))
        return 0
    except HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        print(json.dumps({"ok": False, "code": e.code, "error": body}))
        return 3


if __name__ == "__main__":
    sys.exit(main())
