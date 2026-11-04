"""Saxo sign-in for the live account (Emil, 4 Nov 2026: "live"): OAuth authorization code grant
(developer.saxo, "Authorization Code Grant"). Read-only like `saxo.py`: this only gets tokens.

- `scripts/saxo_login.py` opens Saxo's sign-in in the browser once; Saxo sends the browser back
  to the app's redirect URL on this PC, and the code there is swapped for tokens.
- The access token lasts 20 minutes, the refresh token 40. Each refresh gives a new pair, so a
  session lasts as long as something refreshes it at least every 40 minutes
  (`saxo_sync.py --every`); after a longer gap, sign in again.
- Settings come from the environment, never from a file in a repo: SAXO_APP_KEY,
  SAXO_APP_SECRET, SAXO_REDIRECT (the app's redirect URL, e.g. http://localhost:8799/saxo),
  SAXO_ENV (sim or live), SAXO_AUTH_URL (optional: the AuthenticationUrl in the app details).
- The tokens live in TOKEN_FILE, outside both repos (SAXO_TOKEN_FILE overrides it). Nothing
  here prints a token, a code or the secret.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import secrets
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

AUTH_URLS = {"live": "https://live.logonvalidation.net", "sim": "https://sim.logonvalidation.net"}
TOKEN_FILE = (
    Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "trading-os" / "saxo_token.json"
)
EARLY_S = 60  # refresh this long before the access token runs out


class SignInNeeded(RuntimeError):
    """No usable session: run scripts/saxo_login.py."""


@dataclass(frozen=True)
class App:
    key: str
    secret: str
    redirect: str
    auth_url: str
    env: str

    @classmethod
    def from_env(cls, env: dict[str, Any]) -> App:
        needed = ("SAXO_APP_KEY", "SAXO_APP_SECRET", "SAXO_REDIRECT")
        missing = [k for k in needed if not env.get(k)]
        if missing:
            raise SignInNeeded(f"missing {', '.join(missing)} (docs/SAXO.md)")
        mode = "sim" if str(env.get("SAXO_ENV", "")).lower() == "sim" else "live"
        return cls(
            key=str(env["SAXO_APP_KEY"]),
            secret=str(env["SAXO_APP_SECRET"]),
            redirect=str(env["SAXO_REDIRECT"]),
            auth_url=str(env.get("SAXO_AUTH_URL") or AUTH_URLS[mode]).rstrip("/"),
            env=mode,
        )


def token_file(env: dict[str, Any]) -> Path:
    return Path(env["SAXO_TOKEN_FILE"]) if env.get("SAXO_TOKEN_FILE") else TOKEN_FILE


def authorize_url(app: App, state: str) -> str:
    query = {"response_type": "code", "client_id": app.key, "redirect_uri": app.redirect,
             "state": state}  # fmt: skip
    return f"{app.auth_url}/authorize?{urlencode(query)}"


def new_state() -> str:
    return secrets.token_urlsafe(24)


def _post(app: App, data: dict, http: Any) -> dict:
    basic = base64.b64encode(f"{app.key}:{app.secret}".encode()).decode()
    reply = http.post(
        f"{app.auth_url}/token",
        data=data,
        headers={"Authorization": f"Basic {basic}"},
        timeout=30,
    )
    if not reply.ok:  # never the body: it could echo a code or a token
        raise SignInNeeded(f"Saxo sign-in HTTP {reply.status_code}")
    return reply.json()


def _stamp(reply: dict, now: dt.datetime) -> dict:
    if not reply.get("access_token"):
        raise SignInNeeded("Saxo sent no access token")
    refresh_s = reply.get("refresh_token_expires_in")
    access_s = int(reply.get("expires_in", 1200))
    return {
        "access_token": reply["access_token"],
        "access_until": (now + dt.timedelta(seconds=access_s)).isoformat(),
        "refresh_token": reply.get("refresh_token"),
        "refresh_until": (now + dt.timedelta(seconds=int(refresh_s))).isoformat()
        if refresh_s and reply.get("refresh_token")
        else None,
    }


def exchange_code(
    app: App, code: str, http: Any = requests, now: dt.datetime | None = None
) -> dict:
    """The code from the redirect -> tokens (with their end times, UTC)."""
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": app.redirect}
    return _stamp(_post(app, data, http), now or dt.datetime.now(dt.UTC))


def refresh(app: App, tokens: dict, http: Any = requests, now: dt.datetime | None = None) -> dict:
    data = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
            "redirect_uri": app.redirect}  # fmt: skip
    return _stamp(_post(app, data, http), now or dt.datetime.now(dt.UTC))


def load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def save(path: Path, tokens: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tokens), encoding="utf-8")
    tmp.replace(path)


def _until(tokens: dict, key: str) -> dt.datetime | None:
    v = tokens.get(key)
    return dt.datetime.fromisoformat(v) if v else None


def access_token(
    app: App,
    path: Path,
    http: Any = requests,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> str:
    """A valid access token: the saved one, or a refreshed one (saved again). SignInNeeded when
    neither works."""
    tokens = load(path)
    if not tokens:
        raise SignInNeeded("not signed in: run scripts/saxo_login.py")
    t = now()
    access_end = _until(tokens, "access_until")
    if access_end and t < access_end - dt.timedelta(seconds=EARLY_S):
        return tokens["access_token"]
    refresh_end = _until(tokens, "refresh_until")
    if not tokens.get("refresh_token") or not refresh_end or t >= refresh_end:
        raise SignInNeeded("the Saxo session ended: run scripts/saxo_login.py again")
    fresh = refresh(app, tokens, http, t)
    save(path, fresh)
    return fresh["access_token"]


def session_end(path: Path) -> dt.datetime | None:
    """When the session ends without another refresh (UTC), for the status line."""
    tokens = load(path) or {}
    return _until(tokens, "refresh_until") or _until(tokens, "access_until")
