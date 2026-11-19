"""The Journal notebook's API (`api/notebook.py`) over a synthetic data repo: the sidebar read,
the free pages' routes, the image upload and the hover card. Synthetic data only: tickers are
built from letters, every text is made up."""

import base64

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from tests.test_api import A, B  # noqa: E402
from tests.test_api import data as base_data  # noqa: E402, F401
from tests.test_api_pages import data  # noqa: E402, F401
from trading_os import daily_notes, pages, stock_notes  # noqa: E402


@pytest.fixture
def client(data, monkeypatch):  # noqa: F811
    monkeypatch.setenv("TRADING_OS_NO_LIVE", "1")
    return TestClient(create_app(data))


def log_trade(client) -> None:
    fills = [
        {"date": "2026-06-01", "ticker": A, "side": "buy", "shares": 100, "price": 10.0,
         "setup": "ep_day", "stop": 9.5},
        {"date": "2026-06-10", "ticker": A, "side": "sell", "shares": 100, "price": 11.0},
        {"date": "2026-06-12", "ticker": B, "side": "buy", "shares": 50, "price": 11.0,
         "stop": 10.0},
    ]  # fmt: skip
    for f in fills:
        assert client.post("/api/journal/fills", json=f).status_code == 200


def test_an_empty_repo_gives_an_empty_notebook(client):
    out = client.get("/api/notebook").json()
    assert out["daily"] == [] and out["trades"] == [] and out["pages"] == []
    assert out["stocks"] == [] and out["tags"] == []


def test_the_index_lists_every_kind_with_tags_from_the_text(data, client):  # noqa: F811
    log_trade(client)
    daily_notes.add(data, f"Calm day, ${A} held. #market-tone", None)
    stock_notes.add(data, A, "Flag forming #ep and #watch", None)
    pages.create(data, "Plan", "A page about #ops", ["Weekly"])
    closed = client.get("/api/journal/closed").json()["trades"][0]
    body = {"grade": "A", "notes": "clean #ep entry", "tags": "late", "conviction": 2}
    assert client.put(f"/api/grades/trade/{closed['trade_id']}", json=body).status_code == 200

    out = client.get("/api/notebook").json()
    [day] = out["daily"]
    assert day["stocks"] == [A] and day["tags"] == ["market-tone"]
    [stock] = out["stocks"]
    assert stock["ticker"] == A and stock["tags"] == ["ep", "watch"]
    [page] = out["pages"]
    assert page["title"] == "Plan" and page["tags"] == ["weekly", "ops"]
    by_status = {t["status"]: t for t in out["trades"]}
    done, held = by_status["closed"], by_status["open"]
    assert done["id"] == closed["trade_id"] and done["grade"] == "A" and done["conviction"] == 2
    assert done["tags"] == ["late", "ep"] and done["r"] == pytest.approx(2.0)
    assert done["stop"] == pytest.approx(9.5)
    assert held["ticker"] == B and held["id"] == f"open-{B}-2026-06-12" and held["tags"] == []
    counts = {t["tag"]: t["count"] for t in out["tags"]}
    assert counts["ep"] == 2 and counts["market-tone"] == 1 and counts["late"] == 1
    assert out["tickers"] == sorted({A, B})


def test_an_open_trades_note_is_kept_under_its_own_id(client):
    log_trade(client)
    ref = f"open-{B}-2026-06-12"
    assert client.put(
        f"/api/grades/trade/{ref}", json={"grade": "", "notes": "hold #core"}
    ).is_success
    out = client.get("/api/notebook").json()
    held = next(t for t in out["trades"] if t["status"] == "open")
    assert held["text"] == "hold #core" and held["tags"] == ["core"]


def test_free_pages_are_created_saved_renamed_and_deleted(data, client):  # noqa: F811
    made = client.post("/api/notebook/pages", json={"title": "Rules of thumb"}).json()
    slug = made["slug"]
    assert slug == "rules-of-thumb" and made["text"] == ""
    saved = client.put(f"/api/notebook/pages/{slug}", json={"text": "Wait for the close #rule"})
    assert saved.json()["tags"] == ["rule"]
    renamed = client.put(f"/api/notebook/pages/{slug}", json={"title": "Rules", "tags": ["Core"]})
    assert renamed.json()["title"] == "Rules" and renamed.json()["tags"] == ["core", "rule"]
    assert renamed.json()["text"] == "Wait for the close #rule"  # left out, kept
    assert (pages.folder(data) / f"{slug}.md").is_file()
    assert client.get(f"/api/notebook/pages/{slug}").json()["typed_tags"] == ["core"]
    assert client.delete(f"/api/notebook/pages/{slug}").json() == {"removed": slug}
    assert client.get(f"/api/notebook/pages/{slug}").status_code == 404
    assert client.get("/api/notebook/pages/..%2Fx").status_code == 404
    assert client.put("/api/notebook/pages/nope", json={"text": "x"}).status_code == 404


def test_a_pasted_image_is_stored_with_the_attachments(data, client):  # noqa: F811
    blob = base64.b64encode(b"\x89PNG fake").decode()
    out = client.post(
        "/api/notebook/images", json={"ref": "page one", "name": "p.png", "data": blob}
    ).json()
    assert out["url"] == f"/api/attachments/{out['path']}"
    assert out["path"].startswith("data/journal/attachments/page_one/")
    assert client.get(out["url"]).content == b"\x89PNG fake"
    bad_type = {"ref": "x", "name": "p.exe", "data": blob}
    assert client.post("/api/notebook/images", json=bad_type).status_code == 400
    assert client.post(
        "/api/notebook/images", json={"ref": "x", "name": "p.png", "data": "%%"}
    ).status_code == 400  # fmt: skip


def test_the_hover_card_has_last_change_and_grade(client):
    out = client.get(f"/api/notebook/cards?t={A},{B},NOPE").json()
    assert set(out) == {A, B, "NOPE"}
    assert out[A]["last"] is not None and "chg_pct" in out[A] and "grade" in out[A]
    assert out["NOPE"] == {"last": None, "chg_pct": None, "grade": ""}
