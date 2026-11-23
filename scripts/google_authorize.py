"""One-time consent, to obtain the refresh token the scheduler runs on.

Run this on a machine with a browser, signed in as the Google account whose
calendar the bookings should appear in — Cabmora's own. It prints a refresh
token; put that in Railway and never anywhere else.

    python -m scripts.google_authorize

Google retired the copy-a-code-from-the-page flow in 2022, so this listens on
localhost for the redirect instead. That loopback address must be registered as
an authorised redirect URI on the OAuth client, or Google refuses before the
consent screen is ever shown.
"""

import getpass
import http.server
import json
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser

from app.core.config import get_settings

#: The narrowest scope that can create an event with a Meet conference.
#: `calendar` (full) would also let this credential delete anything in the
#: diary, which is not a power a booking form needs.
SCOPE = "https://www.googleapis.com/auth/calendar.events"

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

_DONE_PAGE = b"""<!doctype html><meta charset="utf-8">
<title>Cabmora</title>
<body style="font-family:system-ui;padding:3rem;max-width:32rem">
<h2 style="font-weight:500">Authorised.</h2>
<p>Close this tab and return to the terminal.</p>
"""


#: Set once the redirect arrives, so the main thread waits instead of spinning.
_received = threading.Event()


class _Catcher(http.server.BaseHTTPRequestHandler):
    """Catches the single redirect Google makes back to us."""

    code: str | None = None
    state: str | None = None

    def do_GET(self) -> None:  # noqa: N802 — stdlib's casing
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Catcher.code = (query.get("code") or [None])[0]
        _Catcher.state = (query.get("state") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_DONE_PAGE)
        _received.set()

    def log_message(self, *args) -> None:
        """Silence the default request logging; it is noise here."""


def main() -> None:
    print("Create an OAuth client (type: Web application) in the Google Cloud")
    print("console, enable the Calendar API, and add this redirect URI:\n")
    print(f"    {REDIRECT_URI}\n")

    # Offered from the environment, because they are almost always already
    # there: this script is run to replace an *expired refresh token*, not to
    # change the OAuth client. Asking for both from scratch every time sent
    # people to `grep` their own .env and left a client secret sitting in
    # terminal scrollback — a worse outcome than the prompt was avoiding.
    settings = get_settings()
    configured_id = (settings.google_client_id or "").strip()
    configured_secret = (settings.google_client_secret or "").strip()

    if configured_id:
        print(f"Client ID [{configured_id}]: ", end="", flush=True)
        client_id = input().strip() or configured_id
    else:
        client_id = input("Client ID: ").strip()

    if configured_secret:
        # Never printed, only offered. Enter accepts what is configured.
        client_secret = (
            getpass.getpass("Client secret [press Enter to use the configured one]: ")
            .strip()
            or configured_secret
        )
    else:
        # Same rule as `_prompt.read_password`: a secret typed at a prompt
        # stays out of shell history and out of `ps` output.
        client_secret = getpass.getpass("Client secret: ").strip()

    if not client_id or not client_secret:
        raise SystemExit("Both the client ID and secret are required.")

    # Guards against a redirect we did not initiate being accepted as ours.
    state = secrets.token_urlsafe(24)
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            # `offline` is what makes Google issue a refresh token at all, and
            # `consent` forces a fresh one even if this account has authorised
            # before — otherwise a re-run returns nothing to store.
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    url = f"{AUTH_URL}?{params}"

    server = http.server.HTTPServer(("localhost", PORT), _Catcher)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print("\nOpening the consent screen. Sign in as the Cabmora account.")
    print(f"If nothing opens, paste this into a browser:\n\n{url}\n")
    webbrowser.open(url)

    # Fifteen minutes, not five. A first-time consent means choosing an
    # account, clicking through the unverified-app interstitial and reading a
    # scope prompt — and if the browser that opens is not the one signed in as
    # the right account, the whole thing restarts. Timing out mid-consent
    # wastes the round trip and teaches nothing.
    if not _received.wait(timeout=900):
        raise SystemExit(
            "Timed out waiting for the consent redirect. Rerun and use the "
            "new URL — the one printed above is tied to this run."
        )

    if _Catcher.state != state:
        raise SystemExit("State mismatch — discarding this response.")
    if not _Catcher.code:
        raise SystemExit("Google returned no authorisation code. Consent denied?")

    body = urllib.parse.urlencode(
        {
            "code": _Catcher.code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body)) as response:
        payload = json.load(response)

    refresh = payload.get("refresh_token")
    if not refresh:
        raise SystemExit(
            "No refresh token in the response. This usually means the account "
            "has authorised before — revoke Cabmora's access at "
            "https://myaccount.google.com/permissions and run this again."
        )

    print("\nSet these on the API service:\n")
    print("MEETING_BACKEND=google")
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print("GOOGLE_CLIENT_SECRET=<the secret you just entered>")
    print(f"GOOGLE_REFRESH_TOKEN={refresh}")
    print("\nTreat the refresh token as a password.")
    print()
    print()
    print("One thing to check before trusting it. This token lasts indefinitely")
    print("only if the OAuth consent screen is published 'In production'. One")
    print("issued while that screen sits in 'Testing' expires after SEVEN DAYS,")
    print("cannot be renewed by the API — Google stamps the deadline on at")
    print("issue — and announces itself solely as a booking that fails.")
    print()
    print("  https://console.cloud.google.com/auth/audience")
    print()
    print("If that page already reads 'In production', this token is good until")
    print("somebody revokes it and there is nothing further to do.")


if __name__ == "__main__":
    main()
