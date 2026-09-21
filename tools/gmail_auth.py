"""Get a Gmail refresh token once, so the app can send as the account.

    python tools/gmail_auth.py

Needs SDOC_GMAIL_CLIENT_ID and SDOC_GMAIL_CLIENT_SECRET in .env / .env.txt -
from an OAuth client of type "Desktop app" in Google Cloud Console. Opens a
browser; sign in as the account the app should send from; the refresh token
is printed at the end, to go into .env and into the host's variables.

Run it on your own machine. It listens on 127.0.0.1 for Google to redirect
back with the authorisation code, so it cannot run on a server.

Asks for gmail.send only - the resulting token can send mail as the account
and cannot read, search or delete anything in it.
"""
import base64
import hashlib
import http.server
import os
import secrets
import socket
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

import sdoc.config  # noqa: E402,F401  - loads .env / .env.txt
from sdoc.mail.gmail_send import SCOPE, TOKEN_URL  # noqa: E402

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def pkce_pair() -> tuple[str, str]:
    """A PKCE verifier and its S256 challenge.

    Proves the process that asked for the code is the one redeeming it, so
    an intercepted code is useless to anyone else.
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(client_id: str, redirect_uri: str, state: str, challenge: str,
                   login_hint: str | None = None) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        # Both needed for a refresh token. Without offline there is none;
        # without consent, a second run returns none because one was
        # already issued.
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint      # pre-selects the right account
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str, verifier: str, redirect_uri: str, client=None) -> dict:
    data = {
        "client_id": os.environ["SDOC_GMAIL_CLIENT_ID"],
        "client_secret": os.environ["SDOC_GMAIL_CLIENT_SECRET"],
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if client is not None:
        response = client.post(TOKEN_URL, data=data)
    else:
        with httpx.Client(timeout=30) as c:
            response = c.post(TOKEN_URL, data=data)
    if response.status_code >= 300:
        raise RuntimeError(f"token exchange failed (HTTP {response.status_code}): "
                           f"{response.text[:300]}")
    body = response.json()
    if "refresh_token" not in body:
        raise RuntimeError("Google returned no refresh token. Remove the app's access at "
                           "myaccount.google.com/permissions and run this again.")
    return body


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    missing = [k for k in ("SDOC_GMAIL_CLIENT_ID", "SDOC_GMAIL_CLIENT_SECRET")
               if not os.environ.get(k)]
    if missing:
        sys.exit("Set " + " and ".join(missing) + " in .env.txt first - from the "
                 "OAuth client (type: Desktop app) in Google Cloud Console.")

    port = _free_port()
    redirect_uri = f"http://127.0.0.1:{port}"
    state = secrets.token_urlsafe(16)
    verifier, challenge = pkce_pair()
    result: dict = {}
    done = threading.Event()

    class Catch(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                result["error"] = "state did not match - the response was not for this request"
            elif "error" in query:
                result["error"] = query["error"][0]
            else:
                result["code"] = query.get("code", [""])[0]
            ok = "code" in result
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((
                "<html><body style='font-family:sans-serif;padding:40px'>"
                + ("<h2>Done - go back to the terminal.</h2>" if ok
                   else f"<h2>Did not work: {result.get('error')}</h2>")
                + "</body></html>").encode())
            done.set()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Catch)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = build_auth_url(os.environ["SDOC_GMAIL_CLIENT_ID"], redirect_uri, state,
                         challenge, os.environ.get("SDOC_MAIL_USER"))
    print("Opening your browser. Sign in as the account the app should send from.")
    print("If it does not open, paste this into one:\n\n  " + url + "\n")
    webbrowser.open(url)

    if not done.wait(timeout=300):
        server.shutdown()
        sys.exit("Timed out waiting for Google after five minutes.")
    server.shutdown()

    if "error" in result:
        sys.exit("Authorisation failed: " + result["error"])

    tokens = exchange_code(result["code"], verifier, redirect_uri)
    print("Got it. Add this line to .env.txt and to the host's variables:\n")
    print("  SDOC_GMAIL_REFRESH_TOKEN=" + tokens["refresh_token"] + "\n")
    print("Treat it like a password: it lets anything holding it send mail as this account.")


if __name__ == "__main__":
    main()
