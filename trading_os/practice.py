"""The practice range (øvebane, Emil, 16 Nov 2026): pick among past signals blind, then see
whether your picks beat taking every signal.

The signals and their bars are an export in the private data repo
(`data/research/practice/signals.parquet`, `bars.parquet`; bars are normalised so the entry
price is 100, `rel_day` 0 is the entry session). Your answers are append-only Parquet files
under `data/practice/answers/`, one per answer, like the journal. A signal is answered at most
once per pool: "practice" (the earlier years) is for training, "exam" (the later years) counts
once. Nothing here holds data; every function takes frames or a data folder.

v2 (17 Nov 2026): each answer also records `note` (your words on the signal) and `shown`
(whether the stock and date were on screen when you answered, so blind and shown results can
be split). A note is edited after the answer by appending to `data/practice/notes/`; old answer
files without these columns load as note "" and shown False. The dates and prices of a signal
are rebuilt from `entry_date`, the NYSE calendar and the signal's `price`.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os.clock import _calendar
from trading_os.store import PARQUET_OPTIONS, unique_stamp

POOLS = ("practice", "exam")
CHOICES = ("skip", "1", "2", "3")
# Size of the position as a share of a normal one: skip is no trade.
MULTIPLIER = {"skip": 0.0, "1": 0.5, "2": 1.0, "3": 1.5}
BIG_WINNER_R = 5.0
ANSWER_COLUMNS = ["signal_id", "pool", "choice", "answered_at", "note", "shown"]
NOTE_COLUMNS = ["signal_id", "note", "saved_ts"]


class AlreadyAnswered(ValueError):
    """A signal can be answered once per pool."""


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "research" / "practice"


def answers_folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "practice" / "answers"


def notes_folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "practice" / "notes"


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


def _with_defaults(frame: pd.DataFrame) -> pd.DataFrame:
    """Answers written before v2 have no note / shown: note "" and shown False."""
    out = frame.copy()
    if "note" not in out:
        out["note"] = ""
    if "shown" not in out:
        out["shown"] = False
    out["note"] = out["note"].fillna("").astype(str)
    out["shown"] = out["shown"].fillna(False).astype(bool)
    return out


def load_answers(data_dir: Path) -> pd.DataFrame:
    files = sorted(answers_folder(data_dir).glob("*.parquet"))
    if not files:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in ANSWER_COLUMNS})
    frames = [_with_defaults(pd.read_parquet(f)) for f in files]
    return pd.concat(frames, ignore_index=True)


def current_notes(data_dir: Path, answers: pd.DataFrame | None = None) -> dict[str, str]:
    """Signal id -> its note now: the latest edit, else the note saved with the answer."""
    answers = load_answers(data_dir) if answers is None else answers
    notes = dict(zip(answers["signal_id"], answers["note"], strict=True))
    files = sorted(notes_folder(data_dir).glob("*.parquet"))
    if files:
        edits = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        for sid, text in edits.sort_values("saved_ts").groupby("signal_id")["note"].last().items():
            notes[sid] = text
    return notes


def save_note(data_dir: Path, signal_id: str, note: str) -> None:
    """Edit the note of an answered signal. Append-only: each edit is its own file and the
    latest wins; the earlier text stays on disk."""
    answers = load_answers(data_dir)
    if not (answers["signal_id"] == signal_id).any():
        raise ValueError("only an answered signal has a note")
    stamp = unique_stamp()
    out = notes_folder(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [{"signal_id": signal_id, "note": str(note), "saved_ts": stamp}], columns=NOTE_COLUMNS
    )
    frame.to_parquet(out / f"{stamp:%Y%m%dT%H%M%S%f}.parquet", **PARQUET_OPTIONS)


def session_dates(entry_date, rel_days) -> list[pd.Timestamp]:
    """The real date of each relative day: rel_day 0 is the entry session, and each step is
    one NYSE session (weekends and holidays are skipped), before or after it."""
    sessions = _calendar("XNYS").sessions
    entry = pd.Timestamp(entry_date).normalize()
    if entry not in sessions:
        raise ValueError(f"{entry.date()} is not an NYSE session")
    at = sessions.get_loc(entry)
    rels = [int(r) for r in rel_days]
    if rels and (at + min(rels) < 0 or at + max(rels) >= len(sessions)):
        raise ValueError("the calendar does not reach that far")
    return [sessions[at + r] for r in rels]


def real_price(normalised, price: float):
    """A normalised price (entry = 100) in dollars: the entry price is `price`."""
    return normalised * float(price) / 100.0


def normalised_price(real, price: float):
    """The inverse of `real_price`: dollars back to the data's entry = 100."""
    return real * 100.0 / float(price)


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


def save_answer(
    data_dir: Path,
    signals: pd.DataFrame,
    signal_id: str,
    pool: str,
    choice: str,
    note: str = "",
    shown: bool = False,
):
    """Append one answer as its own file, with your note and whether the stock and date were
    shown. Refuses a repeat, an unknown signal, a signal of the other pool and a choice outside
    skip / 1 / 2 / 3."""
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
        [
            {
                "signal_id": signal_id,
                "pool": pool,
                "choice": choice,
                "answered_at": stamp,
                "note": str(note),
                "shown": bool(shown),
            }
        ],
        columns=ANSWER_COLUMNS,
    )
    frame.to_parquet(out / f"{stamp:%Y%m%dT%H%M%S%f}.parquet", **PARQUET_OPTIONS)


def _split(joined: pd.DataFrame, mask: pd.Series) -> dict:
    sub = joined[mask]
    taken = int((sub["choice"] != "skip").sum())
    return {"total": len(sub), "taken": taken, "skipped": len(sub) - taken}


def _totals(joined: pd.DataFrame) -> dict:
    n = len(joined)
    picks = float((joined["choice"].map(MULTIPLIER) * joined["net_r"]).sum()) if n else 0.0
    equal = float(joined["net_r"].sum()) if n else 0.0
    return {
        "answered": n,
        "picks_r": picks,
        "equal_r": equal,
        "picks_r_per_signal": picks / n if n else None,
        "equal_r_per_signal": equal / n if n else None,
    }


def stats(signals: pd.DataFrame, answers: pd.DataFrame, pool: str) -> dict:
    """The numbers of one pool, from its answers only.

    `by_choice`: count and mean net R per choice. `picks_r`: total R of your picks (net R times
    the choice's multiplier); `equal_r`: total R of taking every answered signal once at the
    normal size; both also per signal shown. `big` / `losers`: how many >= 5R trades / losing
    trades you took (choice 1-3) and skipped. `by_shown`: the same totals for answers given with
    the stock and date hidden (`blind`) and shown (`shown`)."""
    mine = _with_defaults(answers[answers["pool"] == pool].drop_duplicates("signal_id"))
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
        "by_shown": {
            "blind": _totals(joined[~joined["shown"]]),
            "shown": _totals(joined[joined["shown"]]),
        },
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
