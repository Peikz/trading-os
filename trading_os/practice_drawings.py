"""Lines you draw on a practice chart (Emil, 17 Nov 2026), saved per practice signal.

Separate from the real stocks' `chart_marks`: an append-only event log under
`data/practice/drawings/` (every add and remove is a new file; a line is current while its latest
event is an add), keyed by signal id. A line's two points are (relative day, normalised price),
the practice data's own coordinates, so the same line shows whether the stock and date are
hidden or shown: the chart converts to dates and dollars on the way out and back.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from trading_os.chart_marks import drawn_changes
from trading_os.store import PARQUET_OPTIONS, unique_stamp

COLUMNS = ["mark_id", "action", "signal_id", "x0", "y0", "x1", "y1", "extend", "saved_ts"]


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "practice" / "drawings"


def _write(data_dir: Path, row: dict) -> None:
    out = folder(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row], columns=COLUMNS)
    frame.to_parquet(out / f"{row['saved_ts']:%Y%m%dT%H%M%S%f}.parquet", **PARQUET_OPTIONS)


def add_line(data_dir, signal_id: str, x0: int, y0: float, x1: int, y1: float, extend=False) -> str:
    """Save a line through two (relative day, normalised price) points; returns its id."""
    if int(x0) == int(x1):
        raise ValueError("a line needs two different days")
    stamp = unique_stamp()
    key = "|".join(map(str, ("line", signal_id, x0, y0, x1, y1, stamp.isoformat())))
    mark_id = hashlib.sha1(key.encode()).hexdigest()[:10]
    _write(
        data_dir,
        {
            "mark_id": mark_id,
            "action": "add",
            "signal_id": signal_id,
            "x0": int(x0),
            "y0": float(y0),
            "x1": int(x1),
            "y1": float(y1),
            "extend": bool(extend),
            "saved_ts": stamp,
        },
    )
    return mark_id


def add_level(data_dir, signal_id: str, price: float, start: int, end: int) -> str:
    """A horizontal line at a normalised `price` from relative day `start` to `end`."""
    if not float(price) > 0:
        raise ValueError("a level needs a price above 0")
    return add_line(data_dir, signal_id, start, price, end, price, True)


def remove(data_dir, mark_id: str, signal_id: str) -> None:
    _write(
        data_dir,
        {
            "mark_id": mark_id,
            "action": "remove",
            "signal_id": signal_id,
            "saved_ts": unique_stamp(),
        },
    )


def current(data_dir, signal_id: str) -> pd.DataFrame:
    """This signal's lines whose latest event is an add. Other signals' lines never show."""
    files = sorted(folder(data_dir).glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    events = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    latest = events.sort_values("saved_ts").drop_duplicates("mark_id", keep="last")
    alive = set(latest.loc[latest["action"] == "add", "mark_id"])
    adds = events[events["action"] == "add"].drop_duplicates("mark_id")
    out = adds[adds["mark_id"].isin(alive) & (adds["signal_id"] == signal_id)]
    return out.reset_index(drop=True)


def is_level(mark) -> bool:
    return abs(float(mark["y0"]) - float(mark["y1"])) < 1e-9


def shapes(marks: list[dict], labels: dict[int, str], to_price, last_rel: int) -> list[dict]:
    """The saved lines as chart shapes named "mark:<id>" on the category axis. `labels`: relative
    day -> x label of the bars on screen; `to_price`: normalised price -> the chart's price.
    A line runs from its first day to its second, or on to the last bar when `extend`; one whose
    first day is not on screen is left out, and a line that ends past the screen is cut at the
    last bar."""
    shown = sorted(labels)
    out = []
    for m in marks:
        a, b = sorted(((int(m["x0"]), float(m["y0"])), (int(m["x1"]), float(m["y1"]))))
        (xa, ya), (xb, yb) = a, b
        slope = (yb - ya) / (xb - xa)
        end = last_rel if m.get("extend") else min(xb, last_rel)
        days = [d for d in shown if xa <= d <= end]
        if xa not in labels or len(days) < 2:
            continue
        out.append(
            {
                "type": "line",
                "xref": "x",
                "yref": "y",
                "x0": labels[days[0]],
                "y0": to_price(ya + slope * (days[0] - xa)),
                "x1": labels[days[-1]],
                "y1": to_price(ya + slope * (days[-1] - xa)),
                "name": f"mark:{m['mark_id']}",
                "editable": True,
                "line": {"color": "#e53935", "width": 2},
            }
        )
    return out


def to_marks(report: dict, labels: dict[int, str], to_norm) -> dict:
    """The chart's report (labels and chart prices) in the saved coordinates (relative days and
    normalised prices), ready for `apply_drawn`. `labels`: relative day -> x label."""
    day = {v: k for k, v in labels.items()}

    def conv(s: dict) -> dict:
        return {
            "id": s.get("id"),
            "x0": day.get(str(s["x0"])[:10], day.get(s["x0"])),
            "x1": day.get(str(s["x1"])[:10], day.get(s["x1"])),
            "y0": to_norm(float(s["y0"])),
            "y1": to_norm(float(s["y1"])),
            "past_end": bool(s.get("past_end")),
        }

    return {
        "rendered": {k: conv(dict(v, id=k)) for k, v in (report.get("rendered") or {}).items()},
        "shapes": [conv(s) for s in report.get("shapes") or []],
    }


def apply_drawn(data_dir, signal_id: str, report: dict, labels: dict, to_norm) -> dict[str, int]:
    """Save the chart's report: new lines added (extended when drawn past the last bar), erased
    ones removed, moved ones replaced. Returns counts. `report` is the component's value."""
    if report.get("ticker") != signal_id:
        return {"added": 0, "removed": 0, "moved": 0}
    conv = to_marks(report, labels, to_norm)
    new, erased, moved = drawn_changes(conv["rendered"], conv["shapes"])
    known = current(data_dir, signal_id).set_index("mark_id")
    for s in new:
        add_line(data_dir, signal_id, s["x0"], s["y0"], s["x1"], s["y1"], s["past_end"])
    for mark_id in erased:
        remove(data_dir, mark_id, signal_id)
    for mark_id, s in moved.items():
        keep = bool(known.loc[mark_id, "extend"]) if mark_id in known.index else False
        remove(data_dir, mark_id, signal_id)
        add_line(data_dir, signal_id, s["x0"], s["y0"], s["x1"], s["y1"], keep or s["past_end"])
    return {"added": len(new), "removed": len(erased), "moved": len(moved)}


def describe(mark) -> str:
    if is_level(mark):
        return f"Level at {float(mark['y0']):.2f} (entry = 100)"
    return (
        f"Line day {int(mark['x0'])} at {float(mark['y0']):.2f} → "
        f"day {int(mark['x1'])} at {float(mark['y1']):.2f}"
    )
