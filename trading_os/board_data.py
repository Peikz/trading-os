"""The Today board's data, without any UI (React dashboard, Nov 2026).

What the Streamlit board (`app/board.py`) and the FastAPI app (`api/`) both show: the candidate
queue of the newest runs, each card's facts and key stats, the market tiles, and a stock's daily
bars. Moved here from the app so both front ends call the same code; nothing is computed twice.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import breadth, funds13f, heat, ibd, notify, volume_build

BAR_COLUMNS = ["session_date", "open", "high", "low", "close", "volume"]


def scan_frames(path: str | Path) -> dict[str, pd.DataFrame]:
    """A run's hits split per scan, each with only the columns that scan fills (a run file holds
    every scan's fields, hundreds of columns)."""
    cands = pd.read_parquet(path)
    if cands.empty or "scan" not in cands:
        return {}
    return {
        scan: hits.dropna(axis=1, how="all").reset_index(drop=True)
        for scan, hits in cands.groupby("scan", sort=False)
    }


def exchanges_of(universe_path: str | Path) -> dict[str, str]:
    """Ticker -> exchange from a run's universe snapshot (intraday runs have none)."""
    path = Path(universe_path)
    if not path.exists():
        return {}
    uni = pd.read_parquet(path)
    if "exchange" not in uni:
        return {}
    return dict(zip(uni["ticker"], uni["exchange"], strict=True))


def collect(
    runs, cfg, scan_frames: Callable[[str], dict], exchanges=None, everything: bool = False
) -> pd.DataFrame:
    """The pushed scans' alert-tier hits of the newest pre-market, 10:15, 12:00 and EOD runs,
    newest first, one row per ticker and scan. `everything`: every scan's hits, all tiers, one
    row per ticker (its best grade)."""
    latest = []
    for slot in ("pm", "am", "mid", "eod", "ah"):  # ah: EP-AH (Emil, 27 Oct 2026)
        run = next((r for r in runs if r.slot == slot), None)
        if run is not None:
            latest.append(run)
    # The exchange per ticker from the newest run with a universe file (intraday runs have none)
    listing: dict = {}
    info = pd.DataFrame()
    with_universe = next((r for r in runs if r.universe.exists()), None)
    if exchanges is not None and with_universe is not None:
        listing = exchanges(str(with_universe.universe))
    if with_universe is not None:
        want = ["ticker", "sector", "industry", "float_shares", "earnings_date_next"]
        try:
            info = pd.read_parquet(with_universe.universe, columns=want).drop_duplicates("ticker")
            info = info.set_index("ticker")
        except Exception:  # noqa: BLE001 - the stats strip shows dashes
            info = pd.DataFrame()
    frames = []
    for run in sorted(latest, key=runs.index):
        for scan, hits in scan_frames(str(run.candidates)).items():
            pushed = scan in cfg.scans and cfg.scans[scan].action == "push"
            if not everything and not pushed:
                continue
            alert_only = "tier" in hits and not everything
            shown = hits[hits["tier"] == "alert"] if alert_only else hits
            if shown.empty:
                continue
            if listing and "exchange" not in shown:
                shown = shown.assign(exchange=shown["ticker"].map(listing))
            for column in info.columns:
                if column not in shown:
                    shown = shown.assign(**{column: shown["ticker"].map(info[column])})
            frames.append(
                shown.assign(
                    scan=scan, run_label=run.label, run_slot=run.slot, run_session=run.session
                )
            )
    if not frames:
        return pd.DataFrame()
    out = ibd.relabel(pd.concat(frames, ignore_index=True))
    out = out.drop_duplicates(["ticker", "scan"], keep="first")
    if "grade" not in out:
        out["grade"] = "C"
    out["grade"] = out["grade"].fillna("C")
    out["_g"] = out["grade"].map(notify.GRADE_RANK).fillna(9)
    score = out["grade_score"] if "grade_score" in out else pd.Series(index=out.index)
    out["_s"] = pd.to_numeric(score, errors="coerce").fillna(-1e9)
    out = out.sort_values(["_g", "_s"], ascending=[True, False])
    return out.drop_duplicates("ticker", keep="first") if everything else out


# --- one card


def tags(row: Mapping[str, Any]) -> list[str]:
    """The card's tags: heat, heavily shorted, IBD, a volume build before the day, funds."""
    out = []
    for key in ("heat_tag", "si_tag", "ibd_tag"):
        v = row.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    build = volume_build.card_tag(row)
    if build:
        out.append(build)
    funds = funds13f.card_tag(row)
    if funds:
        out.append(funds)
    return out


def history(row: Mapping[str, Any]) -> str:
    """`📚 812 trades · avg +0.41R · 52% win (2016-26)`: the history behind the grade."""
    n, mean, win = (row.get(f"grade_stat_{k}") for k in ("trades", "mean_r", "win_pct"))
    if n is None or pd.isna(n) or mean is None or pd.isna(mean):
        return ""
    w = f" · {win:.0f}% win" if win is not None and not pd.isna(win) else ""
    return f"📚 {int(n)} trades · avg {mean:+.2f}R{w} (2016-26)"


def card_facts(row: Mapping[str, Any]) -> list[str]:
    """The card's lines under its head: when to buy, the plan (entry, stop, shares, risk), the
    tags, the history and why. Facts only; the decision stays the human's."""
    grade = row.get("grade", "C")
    lines = notify.grade_lines(row) if grade in ("A+++", "A++", "A+", "A", "B") else []
    facts = [*lines[1:2], *notify.plan_lines(row), *tags(row)]
    hist = history(row)
    if hist:
        facts.append(hist)
    why = row.get("grade_why")
    if isinstance(why, str) and why:
        facts.append(f"Why: {why}")
    return facts


def money(x) -> str:
    if x is None or pd.isna(x):
        return "–"
    x = float(x)
    return f"${x / 1e9:.1f}B" if x >= 1e9 else f"${x / 1e6:.0f}M" if x >= 1e6 else f"${x:,.0f}"


def key_stats(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The key stats under the chart (Emil, 26 Oct 2026): market cap, ADR, dollar volume, float,
    % from the 52-week high, RS, the industry and its rank, earnings."""

    def num(k):
        v = row.get(k)
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else v

    chips = [("Mkt cap", money(num("market_cap")))]
    adr = num("adr20_pct")
    chips.append(("ADR", f"{adr:.1f}%" if adr is not None else "–"))
    chips.append(("$ vol 20d", money(num("avg_dollar_volume_20d"))))
    fl = num("float_shares")
    chips.append(("Float", f"{fl / 1e6:,.0f}M" if fl is not None else "–"))
    hi = num("pct_from_52w_high")
    chips.append(("From 52w high", f"{hi:+.0f}%" if hi is not None else "–"))
    rs = num("rs_pct")
    chips.append(("RS", f"{rs:.0f}" if rs is not None else "–"))
    vb = num("vol_build")  # 5-day volume before the day / the 50 before (`volume_build`)
    if vb is not None:
        chips.append(("Vol build", f"{vb:.1f}x"))
    own = num("fund_own")  # 13F shares / shares outstanding, last quarter (`funds13f`)
    if own is not None:
        chips.append(("Funds own", f"{own:.0%}"))
    rank, of = num("industry_rank"), num("industry_of")
    ind = row.get("industry") if isinstance(row.get("industry"), str) else ""
    chips.append(("Industry", f"{ind} #{int(rank)}/{int(of)}" if rank and of else ind or "–"))
    soon = num("earnings_in_sessions")
    nxt = row.get("earnings_date_next")
    if soon is not None:
        chips.append(("Earnings", f"in {int(soon)} sessions"))
    elif nxt is not None and not pd.isna(nxt):
        chips.append(("Earnings", f"{pd.Timestamp(nxt):%d %b}"))
    return chips


def levels(row: Mapping[str, Any]) -> dict[str, float]:
    """The plan's price lines on the chart: entry, stop, and the pivot when there is one."""
    out = {"entry": row.get("plan_entry"), "stop": row.get("plan_stop") or row.get("grade_stop")}
    if row.get("pivot") == row.get("pivot") and row.get("pivot"):
        out["pivot"] = row.get("pivot")
    return {k: float(v) for k, v in out.items() if v is not None and v == v}


# --- the market tiles


def _signed(v) -> str | None:
    return None if v is None or pd.isna(v) else f"{v:+.1f}%"


MARKET_COLOUR = {"Strong": "green", "Mixed": "orange", "Weak": "red"}


def market_word(
    row: Mapping[str, Any] | None, ibd_info: Mapping | None, heat_text: str | None
) -> tuple[str, list[str]]:
    """The market in one word for the top bar's pill (Emil, 4 Nov 2026 redesign), and the
    reasons in plain words. Strong: QQQ light green and a healthy IBD uptrend; weak: QQQ light
    red and an IBD correction; else mixed. A summary of the tracked states, not a rule."""
    light = (row or {}).get("qqq_light")
    state = (ibd_info or {}).get("state")
    dist = (ibd_info or {}).get("dist_count") or 0
    reasons = []
    if light:
        trend = {"GREEN": "up", "YELLOW": "mixed", "RED": "down"}.get(light, "unknown")
        extra = ": few breakout winners" if light == "RED" else ""
        reasons.append(f"Nasdaq trend {trend} · QQQ light {light.lower()}{extra}")
    if heat_text:
        reasons.append(f"Heat: {heat_text}")
    healthy = state == "uptrend" and dist < ibd.PRESSURE_DIST
    if state:
        what = (
            "correction"
            if state == "correction"
            else "healthy uptrend"
            if healthy
            else "uptrend under pressure"
        )
        reasons.append(f"IBD: {what} · {ibd.sell_days(state, dist)} (tracked, not a rule)")
    if light == "GREEN" and healthy:
        word = "Strong"
    elif light == "RED" and state == "correction":
        word = "Weak"
    else:
        word = "Mixed"
    return word, reasons


def tiles(row: Mapping[str, Any], ibd_info: Mapping | None, heat_text: str | None) -> list[tuple]:
    """(label, value, change) per market tile: QQQ light, heat, IBD state, SPY, QQQ, VIX."""
    icons = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}
    light = row.get("qqq_light")
    out = [
        ("QQQ light", f"{icons.get(light, '⚪')} {light or 'n/a'}", None),
        ("Market heat", heat_text or "n/a", None),
        (
            "IBD market",
            ibd.words(ibd_info["state"], ibd_info["dist_count"]) if ibd_info else "n/a",
            ibd.sell_days(ibd_info["state"], ibd_info["dist_count"]) if ibd_info else None,
        ),
    ]
    for name in ("spy", "qqq", "vix"):
        close = row.get(f"{name}_close")
        if close is not None and not pd.isna(close):
            out.append((name.upper(), f"{close:,.2f}", _signed(row.get(f"{name}_chg_pct"))))
    return out


def market_inputs(
    data_dir: Path, runs, today: dt.date | None = None
) -> tuple[dict | None, dict | None, str | None]:
    """(breadth row, IBD state, heat text) for the tiles: the newest EOD breadth row, with the
    pre-market's numbers on top when a pre-market run is newer than that close."""
    latest_eod = next((r for r in runs if r.slot == "eod"), None)
    latest_pm = next((r for r in runs if r.slot == "pm"), None)
    tile_run = latest_pm if latest_pm is not None and latest_pm.breadth_pm is not None else None
    row = None
    if latest_eod is not None and latest_eod.breadth is not None:
        row = pd.read_parquet(latest_eod.breadth).iloc[0].to_dict()
    if tile_run is not None and (latest_eod is None or tile_run.session > latest_eod.session):
        row = {**(row or {}), **pd.read_parquet(tile_run.breadth_pm).iloc[0].to_dict()}
    try:
        ibd_info = ibd.state_at(Path(data_dir), today or dt.date.today())
    except Exception:  # noqa: BLE001 - the tile shows n/a
        ibd_info = None
    heat_lines = heat.short_line(heat.load(Path(data_dir)), (row or {}).get("scan_count"))
    heat_text = heat_lines[0].replace("🌡 ", "") if heat_lines else None
    return row, ibd_info, heat_text


def market_details(row: Mapping[str, Any] | None) -> list[str]:
    """The full market lines under the tiles (the push's market lines)."""
    if not row:
        return []
    try:
        return breadth.push_lines(dict(row))
    except (KeyError, TypeError, ValueError):  # an older or partial row: the tiles still show
        return []


# --- daily bars


def bars_file(data_dir: Path, ticker: str) -> Path | None:
    """The compact 2-year bars file holding `ticker` (the data repo's bars-2y release: one
    small file per first letter, refreshed each morning); older cached copies are removed."""
    from trading_os import remote_data
    from trading_os.bars_pack import shard_of

    pattern = f"bars_2y_*_{shard_of(ticker)}.parquet"
    with contextlib.suppress(Exception):  # offline or gh missing: use what the cache has
        remote_data.fetch(remote_data.repo_of(Path(data_dir)), "bars-2y", pattern)
    files = sorted((remote_data.CACHE / "bars-2y").glob(pattern))
    for old in files[:-1]:
        old.unlink(missing_ok=True)
    return files[-1] if files else None


def ticker_bars(path: Path | None, ticker: str) -> pd.DataFrame:
    """One stock's daily bars from a compact bars file, oldest first."""
    import pyarrow.dataset as ds

    if path is None:
        return pd.DataFrame(columns=BAR_COLUMNS)
    table = ds.dataset(path, format="parquet").to_table(filter=ds.field("ticker") == ticker)
    bars = table.to_pandas()
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    return bars.drop_duplicates("session_date").sort_values("session_date")


def daily_bars(data_dir: Path, ticker: str, live: bool = True) -> pd.DataFrame:
    """One stock's 2-year daily bars: the same source as the Streamlit charts. The bars file is
    refreshed each morning, so during a session `live` adds today's candle so far from
    TradingView (`with_today`)."""
    bars = ticker_bars(bars_file(data_dir, ticker), ticker)
    return with_today(bars, ticker) if live else bars


# --- today's candle (Emil, 11 Nov 2026: "the dashboard graph doesn't update frequently")

TODAY_TTL_S = 60  # TradingView is asked at most once a minute per stock
US_EXCHANGES = ("NASDAQ", "NYSE", "AMEX", "NYSE ARCA", "CBOE", "BATS")
_today_cache: dict[str, tuple[float, dict | None]] = {}


def _session_today(now: dt.datetime | None = None) -> dt.date | None:
    """Today's session date in New York once it has opened (09:30), else None (weekend,
    holiday, before the open)."""
    from trading_os import clock
    from trading_os.config import load_config

    schedule = load_config().schedule
    ny = clock.ny_time(schedule, now or dt.datetime.now(dt.UTC))
    if not clock.is_session(schedule, ny.date()) or ny.time() < dt.time(9, 30):
        return None
    return ny.date()


def _fetch_today(tickers: list[str]) -> dict[str, dict]:
    """ticker -> {open, high, low, close, volume} for the current session, US listings only."""
    from tradingview_screener import Query, col

    fields = ("name", "exchange", "open", "high", "low", "close", "volume")
    query = Query().select(*fields).where(col("name").isin(tickers)).limit(len(tickers) * 4)
    _, raw = query.get_scanner_data(timeout=15)
    raw = raw[raw["exchange"].isin(US_EXCHANGES)].drop_duplicates("name")
    out = {}
    for row in raw.to_dict("records"):
        values = [row.get(k) for k in ("open", "high", "low", "close")]
        if all(isinstance(v, int | float) and v > 0 for v in values):
            out[row["name"]] = {k: float(row[k]) for k in ("open", "high", "low", "close")}
            out[row["name"]]["volume"] = float(row.get("volume") or 0)
    return out


def today_bars(tickers, now: float | None = None, fetch=None) -> dict[str, dict]:
    """Today's candles for several stocks at once, cached `TODAY_TTL_S` seconds per stock.
    Offline or a TradingView error: whatever the cache has (possibly nothing)."""
    import time

    now = time.monotonic() if now is None else now
    wanted = [t for t in dict.fromkeys(tickers) if t]
    stale = [t for t in wanted if now - _today_cache.get(t, (-1e18, None))[0] > TODAY_TTL_S]
    if stale:
        got = {}
        with contextlib.suppress(Exception):
            got = (fetch or _fetch_today)(stale)
        for t in stale:
            _today_cache[t] = (now, got.get(t))
    return {t: _today_cache[t][1] for t in wanted if _today_cache.get(t, (0, None))[1]}


def with_today(
    bars: pd.DataFrame, ticker: str, session: dt.date | None = None, fetch=None
) -> pd.DataFrame:
    """`bars` plus today's candle so far when a session is under way and the file doesn't have
    it yet. The bars file stays the source for every earlier day."""
    session = session or _session_today()
    if session is None or bars.empty or bars["session_date"].max() >= session:
        return bars
    bar = today_bars([ticker], fetch=fetch).get(ticker)
    if bar is None:
        return bars
    row = pd.DataFrame([{"session_date": session, "ticker": ticker, **bar}])
    return pd.concat([bars, row[[c for c in bars.columns if c in row]]], ignore_index=True)


# --- the board's other sources: your watchlists and a screen's results (moved from app/board.py)


def _newest_snapshot(runs) -> tuple[Any, pd.DataFrame]:
    """The newest run with a universe file and that file, one row per ticker, by ticker."""
    with_universe = next((r for r in runs if r.universe.exists()), None)
    if with_universe is None:
        return None, pd.DataFrame()
    uni = pd.read_parquet(with_universe.universe).drop_duplicates("ticker").set_index("ticker")
    return with_universe, uni


def watchlist_names(data_dir) -> list[str]:
    """Your watchlists that have stocks, in the order they were made."""
    from trading_os import my_watchlists

    members = my_watchlists.current(my_watchlists.load(data_dir))
    if members.empty:
        return []
    name_col = "list_name" if "list_name" in members else members.columns[0]
    return list(dict.fromkeys(str(n) for n in members[name_col]))


def watchlist_rows(runs, data_dir, name: str | None = None) -> pd.DataFrame:
    """Your own watchlists' stocks as board rows, with the newest EOD snapshot's numbers; only
    the list `name` when given."""
    from trading_os import my_watchlists

    members = my_watchlists.current(my_watchlists.load(data_dir))
    if members.empty:
        return pd.DataFrame()
    name_col = "list_name" if "list_name" in members else members.columns[0]
    if name is not None:
        members = members[members[name_col].astype(str) == name]
        if members.empty:
            return pd.DataFrame()
    with_universe, uni = _newest_snapshot(runs)
    rows = []
    for m in members.to_dict("records"):
        t = str(m["ticker"])
        base = uni.loc[t].to_dict() if t in uni.index else {}
        rows.append(
            {
                **base,
                "ticker": t,
                "scan": "watchlist",
                "grade": "–",
                "run_label": f"watchlist: {m.get(name_col)}",
                "run_slot": "eod",
                "run_session": with_universe.session if with_universe else None,
            }
        )
    return pd.DataFrame(rows).drop_duplicates("ticker")


def ticker_rows(runs, tickers: list[str], label: str) -> pd.DataFrame:
    """Any stocks as board rows (a screen's results, Emil 29 Oct 2026), in the given order,
    with the newest EOD snapshot's numbers. No grade: a screen is a list, not a tested setup."""
    with_universe, uni = _newest_snapshot(runs)
    rows = [
        {
            **(uni.loc[t].to_dict() if t in uni.index else {}),
            "ticker": t,
            "scan": "screen",
            "grade": "–",
            "run_label": label,
            "run_slot": "eod",
            "run_session": with_universe.session if with_universe else None,
        }
        for t in dict.fromkeys(tickers)
    ]
    return pd.DataFrame(rows)


# --- the Saxo ticket (moved from app/board.py; the order maths is `ticket`)

PRICE_LABELS = {
    "stop": "Trigger price",
    "stop_limit": "Trigger price",
    "limit": "Limit price",
    "limit_ext": "Limit price",
    "market": "Expected price (sizing)",
    "moc": "Expected price (sizing)",
}
UNGRADED_NOTE = "Not graded A+ / A / B: sized as a B for reference (no study edge)."
NO_TICKET = "No ticket: the price must be over the stop, and the plan needs both."
NO_ACCOUNT = "Add settings/account.yaml in the data repo for share sizes."


def plan_session(row: Mapping[str, Any], cfg) -> dt.date:
    """The session the order is for: an EOD find trades the next session."""
    from trading_os import clock

    day = pd.Timestamp(row["run_session"]).date()
    if row.get("run_slot") == "eod":
        return clock.sessions_after(cfg.schedule, day, 1, day + dt.timedelta(days=10))[0]
    return day


def risk_mult(row: Mapping[str, Any], cfg) -> tuple[float, bool]:
    """The grade's risk multiple and whether the row has one (A+ / A / B). Anything else is
    sized as a B for reference."""
    mult = row.get("grade_risk_mult")
    if mult is None or pd.isna(mult):
        mult = cfg.grading["risk_mult"].get(row.get("grade"), 0.0)
    if not mult:
        return float(cfg.grading["risk_mult"].get("B", 1.0)), False
    return float(mult), True


def make_ticket(row: Mapping[str, Any], kind: str, cfg, account, usd_rate: float, price=None):
    """The ticket for `row` as order type `kind` at the grade's risk (`ticket.build`); `price`:
    your own price (else the plan's). None when the plan lacks an entry or a stop."""
    from trading_os import ticket

    mult, _ = risk_mult(row, cfg)
    return ticket.build(
        row,
        kind,
        account.risk_usd(usd_rate) * mult,
        account.size_usd(usd_rate),
        account.max_position_pct,
        price or None,
    )


def ticket_caption(t, usd_rate: float, currency: str) -> str:
    """The line under the ticket: the risk in USD and your currency, the position, the price."""
    return (
        f"Risk {t.risk_usd:,.0f} USD ({t.risk_usd * usd_rate:,.0f} {currency}) · position "
        f"{t.position_usd:,.0f} USD · sized on {t.est_entry:.2f}"
        + (" · capped by your max position" if t.capped else "")
    )


def place_plan(data_dir, row: Mapping[str, Any], cfg, t, kind: str) -> str:
    """'Placed in Saxo': the ticket saved as a plan so the fill matches it in the Journal."""
    from trading_os import plans, ticket

    return plans.create(
        data_dir,
        plan_session(row, cfg),
        str(row["ticker"]),
        "long",
        t.est_entry,
        t.stop,
        t.shares,
        str(row["scan"]),
        f"board: {ticket.ORDER_TYPES[kind]}, {row.get('grade')}",
    )


def fx_rate(data_dir, cfg, currency: str, runs=None) -> float | None:
    """Units of the account currency per USD: live from TradingView, else the rate stored with
    the newest planned alerts, else None (then sizes are not suggested)."""
    from trading_os import dashboard, tv

    if currency == "USD":
        return 1.0
    try:
        return tv.fetch_fx(cfg.sizing["fx_symbol"].format(currency=currency))
    except Exception:  # noqa: BLE001 - offline or TradingView down: the stored rate
        found = runs if runs is not None else dashboard.list_runs(Path(data_dir))
        for run in found[:10]:
            cands = pd.read_parquet(run.candidates)
            if "plan_fx_rate" in cands and cands["plan_fx_rate"].notna().any():
                return float(cands["plan_fx_rate"].dropna().iloc[0])
    return None


# --- Notes & alerts on the focus view

# Green only (Emil, 4 Nov 2026): a stock not worth a look is simply skipped, so red and yellow
# went. Lists already called Flag red / Flag yellow stay as ordinary watchlists.
FLAGS = {"🟩": "Flag green"}


def alert_default(row: Mapping[str, Any]) -> float:
    """A new price alert's level: the pivot, else the plan's entry, else its stop, else 0."""
    for k in ("pivot", "plan_entry", "plan_stop"):
        v = row.get(k)
        with contextlib.suppress(TypeError, ValueError):
            f = float(v)
            if f == f and f:
                return f
    return 0.0


# --- TradingView links and list files (moved from app/streamlit_app.py)


def tradingview_url(ticker: str, exchange: str | None = None) -> str:
    """The stock's TradingView chart (exchange-qualified when known)."""
    symbol = f"{exchange}:{ticker}" if exchange else str(ticker)
    return f"https://www.tradingview.com/chart/?symbol={symbol.replace(':', '%3A')}"


def tradingview_list(tickers, exchanges: Mapping[str, str] | None = None) -> str:
    """A TradingView import (Watchlist → Import list): EXCHANGE:TICKER, comma-separated."""
    listing = {t: e for t, e in (exchanges or {}).items() if isinstance(e, str) and e}
    symbols = [f"{listing[t]}:{t}" if t in listing else str(t) for t in tickers]
    return ",".join(dict.fromkeys(symbols))


# --- the React dashboard's redesign (Emil, 4 Nov 2026): the plan card leads with the decision,
# a "Why" card in plain sentences, one word for the market. Words only; the numbers and rules
# are the study's and the scans', unchanged.

# The study's buy time per entry rule: (New York time, the line in New York time, the line in
# Copenhagen time). The Copenhagen time is worked out per session, so the weeks when only one
# side has moved its clocks are right too.
ENTRY_TIMES = {
    "t_1030": ("10:30", "Buy at {t} New York", "{t} in Copenhagen"),
    "next_1030": ("10:30", "Buy at {t} New York", "{t} in Copenhagen"),
    "t_1015": ("10:15", "Buy after {t} New York", "after {t} in Copenhagen"),
    "t_1200": ("12:00", "Buy after {t} New York", "after {t} in Copenhagen"),
    "next_open": ("09:30", "Buy at the open, {t} New York", "{t} in Copenhagen"),
    "pivot_1000": ("10:00", "Buy-stop at the pivot from {t} New York", "from {t} in Copenhagen"),
    "pm_0915": ("09:15", "Buy pre-market at {t} New York", "{t} in Copenhagen"),
    "close": ("15:45", "Buy at {t} New York, before the close", "{t} in Copenhagen"),
    "ah_1645": ("17:00", "Buy after hours, before {t} New York", "before {t} in Copenhagen"),
    "ah_1800": ("18:00", "Buy after hours at {t} New York", "{t} in Copenhagen"),
}
# Pivot setups without an entry rule: a buy-stop at the pivot (MA-surf from 10:00)
PIVOT_ENTRY = {"ma_surf": "pivot_1000"}
PIVOT_SCANS = ("breakout_watch", "pivot_watch", "vcp", "ma_surf")


def decision(row: Mapping[str, Any], cfg) -> dict | None:
    """The plan card's first line: `Buy at 10:30 New York`, the same moment in Copenhagen, and
    the session it is for. None for anything but A+ / A / B (no study edge, no plan time)."""
    from trading_os import clock

    if row.get("grade") not in ("A+++", "A++", "A+", "A", "B"):
        return None
    if row.get("carried_from") == "ah":  # the morning after: that buy time has passed
        return {
            "text": "Found after hours last night",
            "local": "The study bought at 16:45 New York, before 17:00",
            "session": None,
            "day": None,
        }
    try:
        day = plan_session(row, cfg)
    except (KeyError, TypeError, ValueError, IndexError):
        day = None
    rule = str(row.get("grade_entry_rule") or "") or PIVOT_ENTRY.get(str(row.get("scan")), "")
    out = {"session": day.isoformat() if day else None, "day": f"{day:%a %d %b}" if day else None}
    if rule in ENTRY_TIMES:
        hhmm, ny_text, local_text = ENTRY_TIMES[rule]
        hour, minute = map(int, hhmm.split(":"))
        when = dt.datetime.combine(day or dt.date.today(), dt.time(hour, minute), clock.NEW_YORK)
        local = when.astimezone(clock.COPENHAGEN)
        return out | {
            "text": ny_text.format(t=hhmm),
            "local": local_text.format(t=f"{local:%H:%M}"),
        }
    if row.get("scan") in PIVOT_SCANS:
        pivot = row.get("pivot")
        at = f" {float(pivot):.2f}" if pivot is not None and pivot == pivot else ""
        return out | {"text": f"Buy-stop at the pivot{at}", "local": None}
    return out | {"text": "Buy by the study's plan", "local": None}


def _plain(text: str) -> str:
    """A tag or point without its leading icon, first letter capitalised."""
    text = text.strip()
    while text and not text[0].isalnum() and text[0] not in "$+-":
        text = text[1:].lstrip()
    return text[:1].upper() + text[1:]


def why(row: Mapping[str, Any]) -> dict:
    """The "Why A+" card: the grade's summary (`4 quality points`), each quality point held or
    not, then the exit, the history behind the grade and the tags, as plain sentences."""
    summary = row.get("grade_why")
    points = []
    raw = row.get("grade_points")
    if isinstance(raw, str) and raw:
        for part in raw.split(" · "):
            part = part.strip()
            if part:
                points.append({"ok": not part.startswith("❌"), "text": _plain(part)})
    lines = []
    hold, median = row.get("grade_hold_sessions"), row.get("grade_stat_days_median")
    if hold is not None and not pd.isna(hold):
        tail = f" (median {median:.0f})" if median is not None and not pd.isna(median) else ""
        lines.append(f"Out at the close after {int(hold)} sessions{tail}.")
    else:
        exit_text = notify.EXIT_TEXT.get(str(row.get("grade_exit")), "")
        if exit_text:
            lines.append(_plain(exit_text) + ".")
    n, mean, win = (row.get(f"grade_stat_{k}") for k in ("trades", "mean_r", "win_pct"))
    if n is not None and not pd.isna(n) and mean is not None and not pd.isna(mean):
        won = f"{win:.0f}% won, " if win is not None and not pd.isna(win) else ""
        lines.append(f"{int(n):,} past trades in 2016-26: {won}average {mean:+.2f}R.")
    lines += [_plain(t) for t in tags(row)]
    return {
        "summary": _plain(summary) if isinstance(summary, str) and summary else None,
        "points": points,
        "lines": lines,
    }


MOOD_WORDS = {"green": "Healthy market", "amber": "Cautious market", "red": "Weak market"}
LIGHT_LEVELS = {"GREEN": "green", "YELLOW": "amber", "RED": "red"}


def market_mood(
    row: Mapping[str, Any] | None, ibd_info: Mapping | None, heat_stats: Mapping | None
) -> dict:
    """One word for the market from the three things the push shows (QQQ light, heat, IBD
    state): green when all three are green, red when two or more are red, amber otherwise; with
    each one's reason in plain words. A summary of facts, never a rule: nothing trades on it."""
    row = row or {}
    reasons = []
    light = row.get("qqq_light")
    if isinstance(light, str) and light in LIGHT_LEVELS:
        reasons.append({"level": LIGHT_LEVELS[light], "text": f"QQQ light is {light.lower()}."})
    heat_name = None
    if heat_stats:
        heat_name = heat.band(row.get("scan_count"), heat_stats["bands"])
    if heat_name is not None:
        names = [name for _, name in heat_stats["bands"]]
        k = names.index(heat_name)
        level = "red" if k == 0 else "green" if k == len(names) - 1 else "amber"
        label = heat_stats.get("band_labels", {}).get(heat_name, "")
        count = int(float(row["scan_count"]))
        reasons.append(
            {
                "level": level,
                "text": f"Heat is {heat_name}: {count} stocks up 50 %+ in a quarter"
                + (f" (this band: {label})." if label else "."),
            }
        )
    if ibd_info:
        words = ibd.words(ibd_info["state"], ibd_info["dist_count"])
        if words:
            level = "green" if "🟢" in words else "red" if "🔴" in words else "amber"
            days = ibd.sell_days(ibd_info["state"], ibd_info["dist_count"])
            reasons.append({"level": level, "text": f"IBD: {_plain(words).lower()} ({days})."})
    levels = [r["level"] for r in reasons]
    if not levels:
        mood = None
    elif all(x == "green" for x in levels):
        mood = "green"
    elif levels.count("red") >= 2 or all(x == "red" for x in levels):
        mood = "red"
    else:
        mood = "amber"
    quotes = []
    for name in ("spy", "qqq", "vix"):
        close = row.get(f"{name}_close")
        if close is not None and not pd.isna(close):
            quotes.append(
                {
                    "label": name.upper(),
                    "value": f"{close:,.2f}",
                    "delta": _signed(row.get(f"{name}_chg_pct")),
                }
            )
    return {
        "level": mood,
        "word": MOOD_WORDS.get(mood, "No market data"),
        "reasons": reasons,
        "quotes": quotes,
    }


def next_scan(cfg, now: dt.datetime) -> dict | None:
    """The next scheduled scan (the quiet day's line): its name and start in New York and
    Copenhagen time."""
    from trading_os import clock

    found = clock.next_slot(cfg.schedule, now)
    if found is None:
        return None
    slot, start = found
    names = {"pm": "pre-market scan", "am": "10:15 check", "mid": "12:00 check",
             "eod": "end-of-day scan", "ah": "after-hours scan"}  # fmt: skip
    local = start.astimezone(clock.COPENHAGEN)
    return {
        "slot": slot,
        "name": names.get(slot, slot),
        "when": f"{start:%a %d %b}, {start:%H:%M} New York ({local:%H:%M} in Copenhagen)",
        "at": start.isoformat(),
    }
