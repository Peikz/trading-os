"""Edit a scan's settings in config/scans.yaml from the dashboard (Emil, 22 Oct 2026: "edit
them, maybe even the text"). Only Emil edits, on the Scans page; the rule "never change a
threshold without Emil" holds because the change is his.

The file is full of comments that explain every value, so it is never rewritten: only the
value after `key:` inside the scan's own `{...}` block changes, and a new key (the optional
`label` / `note` text) is added before the block's closing brace. Every edit is checked by
the same validator the jobs use (`parse_config`), and must read back as the value asked for,
before anything is written. Committing and pushing (so GitHub's jobs use it) is a separate
step.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from trading_os.config import DEFAULT_PATH, ConfigError, parse_config

VALUE = r'\[[^\]]*\]|"(?:[^"\\]|\\.)*"|[^,}\n]+'


def format_value(value: Any) -> str:
    """A value as YAML flow text: true/false, numbers, [a, b], "quoted text"."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(format_value(v) for v in value) + "]"
    if isinstance(value, str) and re.fullmatch(r"[a-z_]+", value):
        return value
    return json.dumps(str(value), ensure_ascii=False)  # a JSON string is valid YAML


def _split_comment(line: str) -> tuple[str, str]:
    """(code, comment): the comment starts at a `#` outside quotes."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"' and (i == 0 or line[i - 1] != "\\"):
            quoted = not quoted
        elif ch == "#" and not quoted:
            return line[:i], line[i:]
    return line, ""


def block(text: str, name: str) -> tuple[int, int]:
    """Line range [start, end) of scan `name` under `scans:`."""
    lines = text.splitlines(keepends=True)
    try:
        top = next(i for i, ln in enumerate(lines) if ln.startswith("scans:"))
    except StopIteration as exc:
        raise ConfigError("no scans: section") from exc
    start = None
    for i in range(top + 1, len(lines)):
        ln = lines[i]
        if ln.strip() and not ln.startswith(" ") and not ln.startswith("#"):
            break  # the next top-level section
        if re.match(rf"^  {re.escape(name)}:", ln):
            start = i
            continue
        if start is not None and re.match(r"^  [a-z0-9_]+:", ln):
            return start, i
    if start is None:
        raise ConfigError(f"scan {name!r} not in scans:")
    end = i if lines[i].strip() and not lines[i].startswith(" ") else len(lines)
    return start, end


def set_values(text: str, name: str, changes: Mapping[str, Any]) -> str:
    """`text` with the scan's values changed (new keys added before the closing brace)."""
    lines = text.splitlines(keepends=True)
    start, end = block(text, name)
    todo = dict(changes)
    closing = None
    for i in range(start, end):
        code, comment = _split_comment(lines[i])
        for key in list(todo):
            pattern = rf"(?<![\w])({re.escape(key)}:\s*)({VALUE})"
            text_value = format_value(todo[key])
            new, n = re.subn(pattern, lambda m, v=text_value: m.group(1) + v, code)
            if n:
                code = new
                del todo[key]
        if "}" in code:
            closing = i
        lines[i] = code + comment
    if todo:
        if closing is None:
            raise ConfigError(f"scans.{name}: no {{...}} block to add {sorted(todo)} to")
        code, comment = _split_comment(lines[closing])
        extra = "".join(f",\n     {k}: {format_value(v)}" for k, v in todo.items())
        cut = code.rindex("}")
        lines[closing] = code[:cut] + extra + code[cut:] + comment
    return "".join(lines)


def apply(text: str, name: str, changes: Mapping[str, Any]) -> str:
    """The edited text, validated: it parses like the jobs parse it, and every changed key
    reads back as asked. Raises ConfigError otherwise."""
    new = set_values(text, name, changes)
    cfg = parse_config(yaml.safe_load(new))
    scan = cfg.scans[name]
    got = {"enabled": scan.enabled, "action": scan.action, **dict(scan.params)}
    for key, want in changes.items():
        have = got.get(key)
        have = list(have) if isinstance(have, tuple) else have
        want = list(want) if isinstance(want, tuple) else want
        if have != want:
            raise ConfigError(f"scans.{name}.{key}: wrote {want!r} but it reads {have!r}")
    return new


def diff(old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), "before", "after", n=1
        )
    )


def save(name: str, changes: Mapping[str, Any], path: Path = DEFAULT_PATH) -> str:
    """Write the validated change; returns the diff (empty: nothing changed)."""
    old = Path(path).read_text(encoding="utf-8")
    new = apply(old, name, changes)
    if new != old:
        Path(path).write_text(new, encoding="utf-8", newline="\n")
    return diff(old, new)


def commit_and_push(name: str, path: Path = DEFAULT_PATH) -> tuple[bool, str]:
    """Commit config/scans.yaml in the code repo and push it, so GitHub's jobs use it."""
    repo = Path(path).resolve().parent.parent

    def git(*args: str) -> tuple[bool, str]:
        done = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120
        )
        return done.returncode == 0, (done.stdout + done.stderr).strip()

    rel = Path(path).resolve().relative_to(repo).as_posix()
    if git("diff", "--quiet", "--", rel)[0]:
        return True, "nothing to commit"
    for args in (
        ("add", "--", rel),
        ("commit", "-m", f"config: {name} edited on the dashboard (Emil)", "--", rel),
        ("pull", "--rebase", "--autostash"),
        ("push",),
    ):
        ok, out = git(*args)
        if not ok:
            return False, out
    return True, "committed and pushed"
