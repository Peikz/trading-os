"""Release data on demand (Emil, 20 Oct 2026): the large study files live only on GitHub, in
the private data repo's releases. The dashboard downloads just what a page needs into a cache
folder outside the data repo, capped in size (the files used least recently go first), and
the System health page can empty it. Needs the `gh` CLI signed in on this PC.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

# TRADING_OS_CACHE: the server's fixed cache folder (docs/SERVER.md); else the PC's local app data.
_CACHE_ENV = os.environ.get("TRADING_OS_CACHE")
CACHE = (
    Path(_CACHE_ENV)
    if _CACHE_ENV
    else Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "trading-os-cache"
)
LIMIT_BYTES = int(1.5 * 1024**3)  # the least recently used files go past this


def repo_of(data_dir: Path) -> str:
    """owner/name of the data repo, from its git remote."""
    done = subprocess.run(
        ["git", "-C", str(data_dir), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    url = done.stdout.strip().removesuffix(".git")
    return url.split("github.com/")[-1].split("github.com:")[-1]


def _gh(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)


_listings: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def assets(repo: str, tag: str, max_age: float = 600) -> list[dict]:
    """The release's files (name, size), cached for `max_age` seconds."""
    key = (repo, tag)
    stamp, found = _listings.get(key, (0.0, []))
    if time.time() - stamp < max_age and found:
        return found
    done = _gh(["release", "view", tag, "-R", repo, "--json", "assets"], timeout=60)
    found = json.loads(done.stdout).get("assets", []) if done.returncode == 0 else []
    _listings[key] = (time.time(), found)
    return found


def names(repo: str, tag: str, pattern: str = "*") -> list[str]:
    return sorted(a["name"] for a in assets(repo, tag) if fnmatch.fnmatch(a["name"], pattern))


def fetch(repo: str, tag: str, pattern: str, cache: Path = CACHE) -> list[Path]:
    """Local paths of the release files matching `pattern`, downloading the missing ones."""
    folder = cache / tag
    folder.mkdir(parents=True, exist_ok=True)
    wanted = names(repo, tag, pattern)
    missing = [n for n in wanted if not (folder / n).exists()]
    # Download beside the cache and move each finished file in: a page reading a file while
    # it was still being written saw a broken file ("Parquet magic bytes not found").
    partial = folder / ".partial"
    partial.mkdir(exist_ok=True)
    for k in range(0, len(missing), 100):  # one call per hundred files (each call costs ~1 s)
        batch = [arg for name in missing[k : k + 100] for arg in ("-p", name)]
        _gh(["release", "download", tag, "-R", repo, "-D", str(partial), "--clobber", *batch])
        for name in missing[k : k + 100]:
            done = partial / name
            if done.exists():
                done.replace(folder / name)
    paths = [folder / n for n in wanted if (folder / n).exists()]
    now = time.time()
    for p in paths:  # used just now: the last to be pruned
        os.utime(p, (now, now))
    prune(cache)
    return paths


def prune(cache: Path = CACHE, limit: int = LIMIT_BYTES) -> int:
    """Delete the least recently used files until the cache is under `limit`; returns bytes."""
    files = sorted((p for p in cache.rglob("*") if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    for p in files:
        if total <= limit:
            break
        total -= p.stat().st_size
        p.unlink(missing_ok=True)
    return total


def size(cache: Path = CACHE) -> int:
    return sum(p.stat().st_size for p in cache.rglob("*") if p.is_file()) if cache.exists() else 0


def clear(cache: Path = CACHE) -> None:
    for p in cache.rglob("*"):
        if p.is_file():
            p.unlink(missing_ok=True)
