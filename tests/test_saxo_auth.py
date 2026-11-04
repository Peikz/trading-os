"""Saxo sign-in: the code swap, refresh before the 20 minutes run out, and a clear "sign in
again" once the 40-minute refresh window has passed (a fake token endpoint, no network)."""

import base64
import datetime as dt
from urllib.parse import parse_qs, urlparse

import pytest

from trading_os import saxo, saxo_auth

ENV = {"SAXO_APP_KEY": "key", "SAXO_APP_SECRET": "shh", "SAXO_REDIRECT": "http://localhost:8799/saxo",
       "SAXO_ENV": "live"}  # fmt: skip
NOW = dt.datetime(2026, 11, 5, 14, 0, tzinfo=dt.UTC)


class FakeToken:
    """Saxo's /token: a new access + refresh pair on every call."""

    def __init__(self, status: int = 200):
        self.calls, self.status = [], status

    def post(self, url, data, headers, timeout):
        self.calls.append({"url": url, "data": dict(data), "headers": dict(headers)})
        n, status = len(self.calls), self.status

        class R:
            ok, status_code = status == 200, status

            def json(self):
                return {"access_token": f"a{n}", "token_type": "Bearer", "expires_in": 1200,
                        "refresh_token": f"r{n}", "refresh_token_expires_in": 2400}  # fmt: skip

        return R()


def test_the_sign_in_url_and_the_code_swap():
    app = saxo_auth.App.from_env(ENV)
    url = urlparse(saxo_auth.authorize_url(app, "st"))
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "live.logonvalidation.net" and url.path == "/authorize"
    assert q == {"response_type": "code", "client_id": "key", "redirect_uri": ENV["SAXO_REDIRECT"],
                 "state": "st"}  # fmt: skip
    http = FakeToken()
    tokens = saxo_auth.exchange_code(app, "the-code", http, NOW)
    call = http.calls[0]
    assert call["url"] == "https://live.logonvalidation.net/token"
    assert call["data"] == {"grant_type": "authorization_code", "code": "the-code",
                            "redirect_uri": ENV["SAXO_REDIRECT"]}  # fmt: skip
    assert call["headers"]["Authorization"] == "Basic " + base64.b64encode(b"key:shh").decode()
    assert "shh" not in str(call["data"])  # the secret goes in the header only
    assert tokens["access_until"] == (NOW + dt.timedelta(minutes=20)).isoformat()
    assert tokens["refresh_until"] == (NOW + dt.timedelta(minutes=40)).isoformat()
    sim = saxo_auth.App.from_env(ENV | {"SAXO_ENV": "sim"})
    assert sim.auth_url == "https://sim.logonvalidation.net"
    assert (
        saxo_auth.App.from_env(ENV | {"SAXO_AUTH_URL": "https://x.test/"}).auth_url
        == "https://x.test"
    )


def test_a_saved_token_is_used_then_refreshed_then_sign_in_is_asked(tmp_path):
    app, path, http = saxo_auth.App.from_env(ENV), tmp_path / "t.json", FakeToken()
    saxo_auth.save(path, saxo_auth.exchange_code(app, "c", http, NOW))
    at = lambda m: lambda: NOW + dt.timedelta(minutes=m)  # noqa: E731
    assert saxo_auth.access_token(app, path, http, at(10)) == "a1"  # still fresh: no call
    assert len(http.calls) == 1
    assert saxo_auth.access_token(app, path, http, at(19.5)) == "a2"  # within a minute: refresh
    assert http.calls[1]["data"]["grant_type"] == "refresh_token"
    assert http.calls[1]["data"]["refresh_token"] == "r1"
    assert saxo_auth.load(path)["refresh_token"] == "r2"  # the new pair is saved
    # refreshed at 19.5: its refresh token lasts until 59.5
    with pytest.raises(saxo_auth.SignInNeeded, match="again"):
        saxo_auth.access_token(app, path, http, at(61))
    with pytest.raises(saxo_auth.SignInNeeded, match="not signed in"):
        saxo_auth.access_token(app, tmp_path / "none.json", http, at(0))


def test_errors_never_show_saxos_reply():
    http = FakeToken(status=401)
    with pytest.raises(saxo_auth.SignInNeeded) as exc:
        saxo_auth.exchange_code(saxo_auth.App.from_env(ENV), "c", http, NOW)
    assert str(exc.value) == "Saxo sign-in HTTP 401"
    with pytest.raises(saxo_auth.SignInNeeded, match="SAXO_APP_SECRET"):
        saxo_auth.App.from_env({k: v for k, v in ENV.items() if k != "SAXO_APP_SECRET"})


def test_the_client_takes_the_saved_sign_in_without_saxo_token(tmp_path):
    path = tmp_path / "t.json"
    future = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)
    saxo_auth.save(path, {"access_token": "live-a", "access_until": future.isoformat(),
                          "refresh_token": "r", "refresh_until": future.isoformat()})  # fmt: skip
    client = saxo.client_from_env(ENV | {"SAXO_TOKEN_FILE": str(path)})
    assert client._headers["Authorization"] == "Bearer live-a" and client._base == saxo.LIVE
    with pytest.raises(saxo_auth.SignInNeeded):
        saxo.client_from_env(ENV | {"SAXO_TOKEN_FILE": str(tmp_path / "none.json")})
    assert saxo.client_from_env({"SAXO_TOKEN": "t", "SAXO_ENV": "sim"})._base == saxo.SIM
