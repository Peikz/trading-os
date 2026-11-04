"""Sign in to Saxo once in the browser (docs/SAXO.md; `trading_os/saxo_auth.py`).

uv run python scripts/saxo_login.py

Opens Saxo's sign-in page, waits for Saxo to send the browser back to SAXO_REDIRECT on this PC
(a small local server, closed again right after), swaps the code for tokens and saves them
outside the repos. Prints only when the session ends. Read-only: nothing is sent to Saxo but the
sign-in.
"""

from __future__ import annotations

import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from trading_os import saxo_auth

WAIT_S = 300


def main() -> int:
    env = dict(os.environ)
    try:
        app = saxo_auth.App.from_env(env)
    except saxo_auth.SignInNeeded as exc:
        print(f"Saxo: {exc}")
        return 1
    redirect = urlparse(app.redirect)
    if redirect.hostname not in ("localhost", "127.0.0.1"):
        print("Saxo: SAXO_REDIRECT must be a localhost address on this PC (docs/SAXO.md)")
        return 1
    state = saxo_auth.new_state()
    got: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - the http.server name
            url = urlparse(self.path)
            if url.path != (redirect.path or "/"):
                self.send_response(404)
                self.end_headers()
                return
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            ok = query.get("state") == state and "code" in query
            if ok:
                got["code"] = query["code"]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            text = "Signed in to Saxo. You can close this tab." if ok else "Saxo sign-in failed."
            self.wfile.write(text.encode())

        def log_message(self, *args):  # the URL holds the code: keep it out of the terminal
            return

    server = HTTPServer((redirect.hostname, redirect.port or 80), Handler)
    server.timeout = WAIT_S
    print(f"Saxo ({app.env}): opening the sign-in page in your browser...")
    webbrowser.open(saxo_auth.authorize_url(app, state))
    server.handle_request()
    server.server_close()
    if "code" not in got:
        print("Saxo: no sign-in came back (wrong state, a timeout, or cancelled)")
        return 1
    try:
        tokens = saxo_auth.exchange_code(app, got["code"])
    except saxo_auth.SignInNeeded as exc:
        print(f"Saxo: {exc}")
        return 1
    path = saxo_auth.token_file(env)
    saxo_auth.save(path, tokens)
    end = saxo_auth.session_end(path)
    when = f"{end.astimezone():%H:%M}" if end else "unknown"
    print(f"Saxo ({app.env}): signed in · the session ends at {when} unless refreshed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
