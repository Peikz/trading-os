"""The Streamlit dashboard over the end-to-end fixture (`tests/e2e/make_repo.py`): every page and
every section renders without an exception, offline. The pages and sections are read from the
app itself, so a new one is covered without editing this file. Needs the `app` group
(Streamlit) and runs in CI's e2e job; skipped elsewhere."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.e2e import make_repo, serve  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"
SECTION_KEYS = {"Research": "research_section", "Live results": "live_section",
                "System health": "health_section"}  # fmt: skip


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return make_repo.build(tmp_path_factory.mktemp("e2e"))


@pytest.fixture
def app(built, monkeypatch):
    root, cache = built
    serve.offline(cache, monkeypatch.setattr)
    monkeypatch.setenv("TRADING_OS_DATA", str(root))
    monkeypatch.setenv("TRADING_OS_NO_LIVE", "1")
    for key in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_every_page_and_section_renders(app):
    # The sidebar shows "☀️ Today"; its value is "Today"
    pages = [o.split(" ", 1)[-1] for o in app.sidebar.radio[0].options]
    assert {"Today", "Chart", "Journal", "Research"} <= set(pages)
    for page in pages:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, (page, [e.value for e in app.exception])
        assert app.header, page
        key = SECTION_KEYS.get(page)
        if key is None:
            continue
        sections = list(app.radio(key=key).options)
        assert len(sections) > 1, page
        for section in sections:
            app.radio(key=key).set_value(section).run()
            assert not app.exception, (page, section, [e.value for e in app.exception])


def test_today_shows_the_fixtures_graded_hits(app, built):
    texts = " ".join(str(m.value) for m in app.markdown)
    assert any(t in texts for t in make_repo.TICKERS)
