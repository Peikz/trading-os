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

from trading_os import breadth, heat, ibd, notify

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
    """The card's tags: heat, heavily shorted, IBD."""
    out = []
    for key in ("heat_tag", "si_tag", "ibd_tag"):
        v = row.get(key)
        if isinstance(v, str) and v:
            out.append(v)
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
    lines = notify.grade_lines(row) if grade in ("A+", "A", "B") else []
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


def daily_bars(data_dir: Path, ticker: str) -> pd.DataFrame:
    """One stock's 2-year daily bars: the same source as the Streamlit charts."""
    return ticker_bars(bars_file(data_dir, ticker), ticker)


# --- the board's other sources: your watchlists and a screen's results (moved from app/board.py)


def _newest_snapshot(runs) -> tuple[Any, pd.DataFrame]:
    """The newest run with a universe file and that file, one row per ticker, by ticker."""
    with_universe = next((r for r in runs if r.universe.exists()), None)
    if with_universe is None:
        return None, pd.DataFrame()
    uni = pd.read_parquet(with_universe.universe).drop_duplicates("ticker").set_index("ticker")
    return with_universe, uni


def watchlist_rows(runs, data_dir) -> pd.DataFrame:
    """Your own watchlists' stocks as board rows, with the newest EOD snapshot's numbers."""
    from trading_os import my_watchlists

    members = my_watchlists.current(my_watchlists.load(data_dir))
    if members.empty:
        return pd.DataFrame()
    name_col = "list_name" if "list_name" in members else members.columns[0]
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

FLAGS = {"🟥": "Flag red", "🟨": "Flag yellow", "🟩": "Flag green"}


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
