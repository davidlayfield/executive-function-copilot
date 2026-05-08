#!/usr/bin/env python3
"""
oauth_authorize.py — One-shot Google OAuth authorization for a Desktop client.
Run on a machine that HAS A BROWSER (i.e. your Mac, not Ralph).
The resulting token.json is then uploaded to Ralph via scp.

Usage:
  python3 oauth_authorize.py <oauth_client_desktop.json>

Behavior:
  1. Reads the client_id / client_secret
  2. Spins up a local HTTP server on http://localhost:8765/
  3. Opens your default browser to Google's consent screen with these scopes:
     - https://www.googleapis.com/auth/gmail.readonly
     - https://www.googleapis.com/auth/calendar.readonly
  4. After you click Allow, Google redirects to http://localhost:8765/?code=...
  5. We exchange the code for tokens
  6. Saves token.json next to the input file

After this, scp the token.json to Ralph:
  scp -i ~/.ssh/LightsailDefaultKey-us-east-1.pem token.json \
    ubuntu@100.73.64.27:/home/ubuntu/.clawdbot/credentials/google/<email>/token.json

Stdlib-only. No pip installs needed.
"""
from __future__ import annotations

import http.server
import json
import socketserver
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
PORT = 8765   # change if 8765 is in use


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 oauth_authorize.py <oauth_client_desktop.json>")
        return 1

    client_path = Path(sys.argv[1])
    if not client_path.exists():
        print(f"File not found: {client_path}")
        return 1

    client_data = json.load(open(client_path))
    cfg = client_data.get("installed") or client_data.get("web")
    if not cfg:
        print("ERROR: client JSON has neither 'installed' nor 'web' key")
        return 1

    if "web" in client_data:
        print("⚠️  This is a 'web' OAuth client. Desktop is preferred but web also works.")
        print("    Make sure http://localhost:8765/ is in the client's redirect_uris in GCP console.")

    client_id = cfg["client_id"]
    client_secret = cfg["client_secret"]
    auth_uri = cfg.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")
    token_uri = cfg.get("token_uri", "https://oauth2.googleapis.com/token")
    redirect_uri = f"http://localhost:{PORT}/"

    # Build the consent-screen URL
    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",     # gives us a refresh_token
        "prompt": "consent",          # forces re-consent so we always get refresh_token
    }
    auth_url = f"{auth_uri}?{urlencode(auth_params)}"

    # Set up the localhost callback server
    received: dict[str, str | None] = {"code": None, "error": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            if "code" in qs:
                received["code"] = qs["code"][0]
                self._respond(
                    200,
                    "<h1 style='font-family:sans-serif'>Authorized ✓</h1>"
                    "<p>You can close this tab and return to the terminal.</p>",
                )
            elif "error" in qs:
                received["error"] = qs["error"][0]
                self._respond(400, f"<h1>Error: {qs['error'][0]}</h1>")
            else:
                self._respond(404, "<h1>?</h1>")

        def _respond(self, code: int, body: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, fmt, *args):
            pass

    try:
        httpd = socketserver.TCPServer(("localhost", PORT), Handler)
    except OSError as e:
        print(f"ERROR: cannot bind to localhost:{PORT}: {e}")
        print("Edit PORT at the top of this script and try again.")
        return 1

    server_thread = threading.Thread(target=httpd.handle_request, daemon=True)
    server_thread.start()

    print(f"\n📋 Opening your browser to authorize...")
    print(f"   If it doesn't open, paste this URL manually:\n   {auth_url}\n")
    print(f"   Listening on {redirect_uri} for the redirect...")

    if not webbrowser.open(auth_url):
        print("⚠️  webbrowser.open returned False — paste the URL above into your browser.")

    # Wait for the callback (max 5 minutes)
    deadline = time.time() + 300
    while time.time() < deadline:
        if not server_thread.is_alive():
            break
        time.sleep(0.5)

    httpd.server_close()

    if received["error"]:
        print(f"\n❌ OAuth error: {received['error']}")
        return 1
    if not received["code"]:
        print("\n❌ Timed out waiting for OAuth callback.")
        return 1

    # Exchange the code for tokens
    print("✅ Code received. Exchanging for token...")
    body = urlencode({
        "code": received["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = Request(
        token_uri,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
    )
    with urlopen(req, timeout=30) as resp:
        token_payload = json.loads(resp.read().decode())

    # Save in BOTH formats so it works with whatever GoogleAuth class expects:
    #   - Google library format (google.oauth2.credentials.Credentials)
    #   - Raw OAuth response
    expires_at = (datetime.now(timezone.utc) +
                  timedelta(seconds=token_payload.get("expires_in", 3599))).isoformat()
    token_data = {
        # google-auth library format (what most Python OAuth code expects)
        "token":          token_payload.get("access_token"),
        "refresh_token":  token_payload.get("refresh_token"),
        "token_uri":      token_uri,
        "client_id":      client_id,
        "client_secret":  client_secret,
        "scopes":         SCOPES,
        "expiry":         expires_at,
        # Also include raw OAuth field names for compatibility with custom auth classes
        "access_token":   token_payload.get("access_token"),
        "expires_in":     token_payload.get("expires_in"),
        "expires_at":     expires_at,
        "token_type":     token_payload.get("token_type", "Bearer"),
        "scope":          token_payload.get("scope"),
    }

    out_path = client_path.parent / "token.json"
    json.dump(token_data, open(out_path, "w"), indent=2)

    print(f"\n✅ Saved token.json to {out_path}")
    print(f"   Scopes granted: {token_payload.get('scope')}")
    print(f"   Expires in: {token_payload.get('expires_in')}s")
    print(f"   Refresh token present: {'refresh_token' in token_payload}")
    print()
    print("Next: upload to Ralph (if you ran this on a non-Ralph machine):")
    parent_name = client_path.parent.name
    print(f"  scp -i ~/.ssh/LightsailDefaultKey-us-east-1.pem {out_path} \\")
    print(f"    ubuntu@100.73.64.27:/home/ubuntu/.clawdbot/credentials/google/{parent_name}/token.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
