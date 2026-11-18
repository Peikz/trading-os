"""Serve the React dashboard and its API on ONE port, on this machine only, over your data repo:

    uv run --group api python -m api.serve --port 8600

The API (`api.main.create_app`) answers `/api/...`; the built app (`web/dist`, from
`npm run build`) answers everything else, the way Caddy serves them on the server
(deploy/Caddyfile). Bound to 127.0.0.1: nothing else on the network can reach it.
`scripts/start_web.ps1` builds the app when it is missing or older than its sources and
starts this. The data folder is `--data`, else env TRADING_OS_DATA, else `../trading-os-data`
next to this checkout (where the Streamlit app looks too).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "web" / "dist"


def make_app(data: Path, dist: Path = DIST):
    from fastapi.staticfiles import StaticFiles

    from api.main import create_app

    app = create_app(data)
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8600)
    parser.add_argument("--data", type=Path, help="the data repo (default: env TRADING_OS_DATA)")
    args = parser.parse_args()
    data = args.data or Path(os.environ.get("TRADING_OS_DATA") or REPO.parent / "trading-os-data")
    data = data.resolve()
    if not (data / "data").exists():
        parser.error(f"No data folder at {data}: clone the data repo there or pass --data.")
    if not (DIST / "index.html").exists():
        parser.error(
            "web/dist is missing: run `npm run build` in web/ (scripts/start_web.ps1 does)."
        )
    print(f"Trading OS on http://127.0.0.1:{args.port}  (data: {data})")
    uvicorn.run(make_app(data), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
