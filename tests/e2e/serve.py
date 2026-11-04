"""The end-to-end tests' server: the real API (`api.main.create_app`) over a fresh synthetic
data repo (`tests/e2e/make_repo.py`), plus the built React app (`web/dist`) on the same origin,
the way Caddy serves them on the server (deploy/Caddyfile).

    uv run --group api python -m tests.e2e.serve --port 8765

Like the server image (deploy/api.Dockerfile), the scans config is a read-only copy outside a
git checkout, so the Scans page is view-only. Offline: release files come only from the
fixture's cache folder (no `gh` call), the Screener's live data and the Market page's live
sectors are off, and Alpaca keys are removed from the environment.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DIST = REPO / "web" / "dist"


def offline(cache: Path, patch=setattr) -> None:
    """Release files: only what the fixture put in the cache, never a download; GitHub's run
    list is synthetic. `patch`: pytest's `monkeypatch.setattr` to undo it after a test."""
    from trading_os import remote_data

    patch(remote_data, "CACHE", cache)

    def names(repo, tag, pattern="*"):
        return sorted(p.name for p in (cache / tag).glob(pattern))

    def fetch(repo, tag, pattern, cache_dir=cache):
        return sorted((cache / tag).glob(pattern))

    patch(remote_data, "names", names)
    patch(remote_data, "fetch", fetch)
    patch(remote_data, "repo_of", lambda data_dir: "synthetic/data-repo")

    import datetime as dt

    import pandas as pd

    from trading_os import health

    def run_list(limit: int = 100) -> pd.DataFrame:  # System health's GitHub runs, no gh call
        now = dt.datetime.now(dt.UTC)
        return pd.DataFrame([
            {"workflowName": "CI", "event": "push", "status": "completed",
             "conclusion": "success", "createdAt": (now - dt.timedelta(hours=h)).isoformat(),
             "updatedAt": now.isoformat()}
            for h in (1, 2)
        ])  # fmt: skip

    patch(health, "run_list", run_list)


def view_only_config(folder: Path) -> Path:
    """Read-only copies of config/scans.yaml and runs.yaml, as baked into the server image."""
    from trading_os import scans_view, timer
    from trading_os.config import DEFAULT_PATH

    path = folder / "config" / "scans.yaml"
    path.parent.mkdir(parents=True)
    for source, target in ((DEFAULT_PATH, path), (timer.RUNS_PATH, path.with_name("runs.yaml"))):
        shutil.copy(source, target)
        target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    if os.geteuid() == 0:  # root may write any file; the image runs as an unprivileged user
        editable = scans_view.editable

        def as_app_user(p):
            writable, checkout = editable(p)
            return writable and bool(Path(p).stat().st_mode & stat.S_IWUSR), checkout

        scans_view.editable = as_app_user
    return path


def make_app(out: Path):
    from fastapi.staticfiles import StaticFiles

    from tests.e2e import make_repo

    os.environ["TRADING_OS_NO_LIVE"] = "1"
    for key in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"):
        os.environ.pop(key, None)
    root, cache = make_repo.build(out)
    offline(cache)
    config = view_only_config(out / "image")

    from api.main import create_app

    app = create_app(root, config)
    if DIST.exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--out", type=Path, help="where to write the repo (default: a temp dir)")
    args = parser.parse_args()
    out = (args.out or Path(tempfile.mkdtemp(prefix="trading-os-e2e-"))).resolve()
    # Pull latest / Save & push run git in the data folder: never inside this checkout
    if out.is_relative_to(REPO):
        parser.error("--out must be outside the code repo (Save & push runs git there)")
    if (out / "image").exists():
        for name in ("scans.yaml", "runs.yaml"):
            with contextlib.suppress(FileNotFoundError):
                (out / "image" / "config" / name).chmod(0o644)
        shutil.rmtree(out / "image")
    app = make_app(out)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
