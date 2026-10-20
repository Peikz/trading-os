"""The Chart page's drawable chart (Emil, 20 Oct 2026): the same Plotly figure, shown by a
small custom component (components/chart_draw) that reports the lines you draw, move or
erase. The page saves the changes with `chart_marks.apply_drawn`.

The component loads Plotly's JavaScript from the plotly Python package, copied next to it on
start (kept out of git), so it always matches the figures the package builds.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import plotly
import streamlit.components.v1 as components

HERE = Path(__file__).parent / "components" / "chart_draw"


def _plotly_js() -> None:
    src = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    dst = HERE / "plotly.min.js"
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copyfile(src, dst)


_plotly_js()
_component = components.declare_component("chart_draw", path=str(HERE))


def chart_draw(fig, *, ticker: str, config: dict, key: str, height: int = 640):
    """Show `fig`; returns the latest report of its lines (None until you draw):
    {seq, ticker, rendered: {mark id: points}, shapes: [{id, x0, y0, x1, y1, past_end}]}."""
    return _component(
        fig=fig.to_json(), ticker=ticker, config=config, height=height, key=key, default=None
    )
