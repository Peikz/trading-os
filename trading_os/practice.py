"""The practice range (øvebane, Emil, 16 Nov 2026): pick among past signals blind, then see
whether your picks beat taking every signal.

The signals and their bars are an export in the private data repo
(`data/research/practice/signals.parquet`, `bars.parquet`; bars are normalised so the entry
price is 100, `rel_day` 0 is the entry session). Your answers are append-only Parquet files
under `data/practice/answers/`, one per answer, like the journal. A signal is answered at most
once per pool: "practice" (the earlier years) is for training, "exam" (the later years) counts
once. Nothing here holds data; every function takes frames or a data folder.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os.store import PARQUET_OPTIONS, unique_stamp

POOLS = ("practice", "exam")
CHOICES = ("skip", "1", "2", "3")
# Size of the position as a share of a normal one: skip is no trade.
MULTIPLIER = {"skip": 0.0, "1": 0.5, "2": 1.0, "3": 1.5}
BIG_WINNER_R = 5.0
ANSWER_COLUMNS = ["signal_id", "pool", "choice", "answered_at"]


class AlreadyAnswered(ValueError):
    """A signal can be answered once per pool."""


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "research" / "practice"


def answers_folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "practice" / "answers"


def available(data_dir: Path) -> bool:
    return (folder(data_dir) / "signals.parquet").exists() and (
        folder(data_dir) / "bars.parquet"
    ).exists()


def load_signals(data_dir: Path) -> pd.DataFrame:
    return pd.read_parquet(folder(data_dir) / "signals.parquet")


def load_bars(data_dir: Path, signal_id: str) -> pd.DataFrame:
    """The bars of one signal, oldest first (a filtered read: the file is large)."""
    bars = pd.read_parquet(
        folder(data_dir) / "bars.parquet", filters=[("signal_id", "==", signal_id)]
    )
    return bars.sort_values("rel_day").reset_index(drop=True)


def visible_bars(bars: pd.DataFrame, answered: bool) -> pd.DataFrame:
    """Before the answer only the sessions before the entry session: the entry session's bar
    would show how the trade went. After it, everything."""
    shown = bars if answered else bars[bars["rel_day"] < 0]
    return shown.sort_values("rel_day").reset_index(drop=True)


def load_answers(data_dir: Path) -> pd.DataFrame:
    files = sorted(answers_folder(data_dir).glob("*.parquet"))
    if not files:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in ANSWER_COLUMNS})
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def unseen(signals: pd.DataFrame, answers: pd.DataFrame, pool: str) -> pd.DataFrame:
    """The pool's signals not yet answered in this pool."""
    done = set(answers.loc[answers["pool"] == pool, "signal_id"])
    return signals[(signals["pool"] == pool) & ~signals["signal_id"].isin(done)]


def next_signal(
    signals: pd.DataFrame,
    answers: pd.DataFrame,
    pool: str,
    rng: random.Random | None = None,
) -> str | None:
    """A random unseen signal id of the pool, or None when the pool is used up."""
    left = unseen(signals, answers, pool)["signal_id"].tolist()
    if not left:
        return None
    return (rng or random).choice(left)


def save_answer(data_dir: Path, signals: pd.DataFrame, signal_id: str, pool: str, choice: str):
    """Append one answer as its own file. Refuses a repeat, an unknown signal, a signal of the
    other pool and a choice outside skip / 1 / 2 / 3."""
    if choice not in CHOICES:
        raise ValueError(f"choice must be one of {CHOICES}, got {choice!r}")
    row = signals[signals["signal_id"] == signal_id]
    if row.empty or row.iloc[0]["pool"] != pool:
        raise ValueError("that signal is not in this pool")
    existing = load_answers(data_dir)
    if ((existing["signal_id"] == signal_id) & (existing["pool"] == pool)).any():
        raise AlreadyAnswered(signal_id)
    stamp = unique_stamp()
    out = answers_folder(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [{"signal_id": signal_id, "pool": pool, "choice": choice, "answered_at": stamp}],
        columns=ANSWER_COLUMNS,
    )
    frame.to_parquet(out / f"{stamp:%Y%m%dT%H%M%S%f}.parquet", **PARQUET_OPTIONS)


def _split(joined: pd.DataFrame, mask: pd.Series) -> dict:
    sub = joined[mask]
    taken = int((sub["choice"] != "skip").sum())
    return {"total": len(sub), "taken": taken, "skipped": len(sub) - taken}


def stats(signals: pd.DataFrame, answers: pd.DataFrame, pool: str) -> dict:
    """The numbers of one pool, from its answers only.

    `by_choice`: count and mean net R per choice. `picks_r`: total R of your picks (net R times
    the choice's multiplier); `equal_r`: total R of taking every answered signal once at the
    normal size; both also per signal shown. `big` / `losers`: how many >= 5R trades / losing
    trades you took (choice 1-3) and skipped."""
    mine = answers[answers["pool"] == pool].drop_duplicates("signal_id")
    joined = mine.merge(signals[["signal_id", "net_r"]], on="signal_id", how="inner")
    n = len(joined)
    by_choice = {}
    for c in CHOICES:
        sub = joined[joined["choice"] == c]
        by_choice[c] = {
            "count": len(sub),
            "mean_r": float(sub["net_r"].mean()) if len(sub) else None,
        }
    picks = float((joined["choice"].map(MULTIPLIER) * joined["net_r"]).sum()) if n else 0.0
    equal = float(joined["net_r"].sum()) if n else 0.0
    return {
        "pool": pool,
        "answered": n,
        "by_choice": by_choice,
        "picks_r": picks,
        "equal_r": equal,
        "picks_r_per_signal": picks / n if n else None,
        "equal_r_per_signal": equal / n if n else None,
        "big": _split(joined, joined["net_r"] >= BIG_WINNER_R),
        "losers": _split(joined, joined["net_r"] < 0),
        "remaining": len(unseen(signals, answers, pool)),
        "pool_size": int((signals["pool"] == pool).sum()),
    }


def _num(x, fmt: str) -> str:
    return "n/a" if x is None or not np.isfinite(x) else fmt.format(x)


def card_facts(row: pd.Series) -> list[tuple[str, str]]:
    """The facts shown on the card, all known at the entry: label and text."""
    dvol = row.get("dollar_vol_20d")
    return [
        ("Setup", str(row["setup_name"])),
        ("Grade", str(row["grade"])),
        ("Gap at entry", _num(row.get("gap_pct"), "{:+.1f} %")),
        ("Volume, day before / 50-day avg", _num(row.get("rvol_prev_day"), "{:.1f}x")),
        ("Dollar volume, 20-day avg", _num(None if dvol is None else dvol / 1e6, "{:,.1f} M$")),
        ("Price band", f"${row['price_band']}"),
        ("ADR (20 days)", _num(row.get("adr_pct"), "{:.1f} %")),
        ("From 52-week high", _num(row.get("dist_52w_high_pct"), "{:+.1f} %")),
        ("Stop distance", f"{row['stop_pct']:.1f} %"),
        ("Grade rule", str(row.get("grade_rule") or "n/a").replace("_", " ")),
    ]
