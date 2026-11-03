"""One git operation at a time on the data repo clone (deploy/, Hetzner prep, Nov 2026).

On the server three containers share one clone: `data-sync` pulls every 10 minutes, the API
pulls and pushes on *Save & push*, and the `alerts` service pulls every 5 minutes and pushes
what fired. Two of them running git at once can collide on `.git/index.lock` or on a rebase in
progress, so every pull and push takes this lock first.

The lock is a file inside the clone's `.git` folder (never tracked, never pushed), held with
`flock`; `deploy/data-sync.sh` takes the same file with the `flock` command. It is reentrant
within one thread, so `save_and_push` can call `pull` while holding it. On Windows (the PC)
there is no `fcntl`: the lock then only serializes threads of the one process.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

LOCK_NAME = "trading-os-git.lock"
WAIT_S = 600.0  # a pull of the data repo takes seconds; ten minutes means something is stuck

_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_depth = threading.local()


def lock_path(data_dir: Path) -> Path:
    git_dir = Path(data_dir) / ".git"
    return (git_dir if git_dir.is_dir() else Path(data_dir)) / LOCK_NAME


def _thread_lock(key: str) -> threading.RLock:
    with _guard:
        return _locks.setdefault(key, threading.RLock())


@contextmanager
def held(data_dir: Path, wait_s: float = WAIT_S, poll_s: float = 0.2) -> Iterator[None]:
    """Hold the data repo's git lock; raises TimeoutError after `wait_s` seconds."""
    path = lock_path(data_dir)
    key = str(path.resolve())
    local = _thread_lock(key)
    if not local.acquire(timeout=wait_s):
        raise TimeoutError("the data repo is busy")
    depths = _depth.__dict__.setdefault("by_path", {})
    handle = None
    try:
        if depths.get(key, 0) == 0 and fcntl is not None and path.parent.is_dir():
            handle = path.open("a")
            deadline = time.monotonic() + wait_s
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("the data repo is busy") from None
                    time.sleep(poll_s)
        depths[key] = depths.get(key, 0) + 1
        try:
            yield
        finally:
            depths[key] -= 1
    finally:
        if handle is not None:
            fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()
        local.release()
