"""The Scans page's data, without any UI (React dashboard, Nov 2026): moved from
`app/streamlit_app.py`. Every scan with when it runs (New York · Copenhagen), when its hits
are pushed, how it is graded and its settings; and the edit form's fields and the change it
makes. Saving goes through `scan_editor` (validated like the jobs validate config); only Emil
edits, on the Scans page, so the rule "never change a threshold without Emil" holds.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from trading_os import clock, dashboard, notify

HIDDEN = {"push_tier", "push_slot", "push_ungraded", "label", "note"}
CAPTION = (
    "Every scan: when it runs, when its hits are pushed, how it is graded and its settings. "
    "Edit one below: the change is checked like the jobs check it, saved to config/scans.yaml "
    "where the dashboard runs, and used by GitHub's jobs after Commit & push. A run's times "
    "change under Edit a run above."
)
PUSH_SLOTS = ("at its run", "next pre-market", "both")


NOT_WRITABLE = (
    "View only here: config/scans.yaml can't be written where the dashboard runs (on the "
    "server it is part of the image). Edit scans on the PC dashboard, or see deploy/DEPLOY.md."
)
NOT_A_CHECKOUT = (
    "Saved here, but Commit & push needs config/scans.yaml in a git checkout of the code repo "
    "with push rights."
)


def editable(path: Path) -> tuple[bool, bool]:
    """(can the dashboard write config/scans.yaml here, is it in a git checkout to push from)."""
    path = Path(path)
    writable = path.is_file() and os.access(path, os.W_OK)
    checkout = (path.resolve().parent.parent / ".git").exists()
    return writable, checkout


def label(cfg, name: str) -> str:
    return cfg.scans[name].params.get("label") or notify.SCAN_LABELS.get(name, name)


def runs_text(scan, today: dt.date) -> str:
    parts = []
    for slot in scan.slots:
        start = dashboard.slot_start(slot, today)
        parts.append(f"{slot} {clock.both_times(start)}" if start else slot)
    return " · ".join(parts)


def pushed_text(scan) -> str:
    if scan.action != "push":
        return "saved only"
    if scan.name == "breadth":
        return "market lines of the EOD push"
    names = {"pm": "next pre-market 07:17"}
    parts = ["at its run" if s in scan.slots else names.get(s, s) for s in notify.push_slots(scan)]
    return " + ".join(dict.fromkeys(parts))


def best_grade(text: str) -> int:
    """Best grade a scan can give first, C last, lists and unpushed scans after."""
    found = re.findall(r"A\+|\bA\b|\bB\b|\bC\b", text)
    return min((notify.GRADE_RANK[g] for g in found), default=4 if text != "-" else 5)


def table(cfg, today: dt.date | None = None) -> list[dict[str, Any]]:
    """One row per scan, the best grade it can give first (config order within a grade)."""
    today = today or clock.ny_time(cfg.schedule, dt.datetime.now(dt.UTC)).date()
    graded = {}
    for strategy, rule in (cfg.grading.get("quality") or {}).items():
        grades = ", ".join(f"{g} at {pts}+ points" for pts, g in rule.get("grades", []))
        for live in rule.get("live_scans", []):
            graded[live] = f"{grades} ({strategy})"
    rows = []
    for name, scan in cfg.scans.items():
        if scan.action != "push" or name == "breadth":
            grade = "-"
        elif scan.slot == "weekly":
            grade = "list, shown in full"
        else:
            grade = graded.get(name) or (
                "C, pushed in full" if scan.params.get("push_ungraded") else "C (only counted)"
            )
        settings = ", ".join(f"{k} {v}" for k, v in scan.params.items() if k not in HIDDEN)
        rows.append(
            {
                "scan": label(cfg, name),
                "on": scan.enabled,
                "runs (NY · CPH)": runs_text(scan, today),
                "pushed": pushed_text(scan),
                "grade": grade,
                "settings": settings,
                "note": scan.params.get("note", ""),
                "key": name,
            }
        )
    rows.sort(key=lambda r: best_grade(r["grade"]))
    return rows


def push_options(scan) -> dict[str, Any]:
    own = scan.slots[0]
    return {"at its run": [own], "next pre-market": "pm", "both": [own, "pm"]}


def form(cfg, name: str) -> dict[str, Any]:
    """The edit form's fields for one scan: on/off, pushed or saved only, when it is pushed
    (scans with `push_slot`), every number and on/off setting, its name and note in the push."""
    scan = cfg.scans[name]
    params = dict(scan.params)
    push = None
    if "push_slot" in params:
        current = params["push_slot"]
        current = list(current) if isinstance(current, tuple) else current
        options = push_options(scan)
        names = [k for k, v in options.items() if v == current or [v] == current]
        push = names[0] if names else PUSH_SLOTS[0]
    numbers = [
        {"key": k, "value": v, "kind": "int" if isinstance(v, int) else "float"}
        for k, v in params.items()
        if k not in HIDDEN and not isinstance(v, bool) and isinstance(v, int | float)
    ]
    flags = [{"key": k, "value": v} for k, v in params.items()
             if k not in HIDDEN and isinstance(v, bool)]  # fmt: skip
    return {
        "name": name,
        "label": label(cfg, name),
        "enabled": scan.enabled,
        "action": scan.action,
        "push": push,
        "numbers": numbers,
        "flags": flags,
        "push_label": params.get("label", ""),
        "note": params.get("note", ""),
    }


def changes(cfg, name: str, new: Mapping[str, Any]) -> dict[str, Any]:
    """What the form changes (`scan_editor.save` takes it): only keys whose value differs.
    `new` may hold enabled, action, push (a PUSH_SLOTS name), the numbers and flags by key,
    label and note. Numbers keep their type (int stays int)."""
    scan = cfg.scans[name]
    params = dict(scan.params)
    before = {"enabled": scan.enabled, "action": scan.action, **params}
    wanted: dict[str, Any] = {}
    for key, value in new.items():
        if key == "push":
            if "push_slot" in params and value is not None:
                wanted["push_slot"] = push_options(scan)[value]
            continue
        if key in ("enabled", "action", "label", "note"):
            wanted[key] = value
        elif key in params and key not in HIDDEN:
            old = params[key]
            if isinstance(old, bool):
                wanted[key] = bool(value)
            elif isinstance(old, int):
                wanted[key] = int(value)
            elif isinstance(old, float):
                wanted[key] = float(value)
    out = {}
    for key, value in wanted.items():
        old = before.get(key, "" if key in ("label", "note") else None)
        old = list(old) if isinstance(old, tuple) else old
        if value != old:
            out[key] = value
    return out
