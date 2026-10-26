"""A fast daily chart for the focus view (Emil, 26 Oct 2026): TradingView's open-source
Lightweight Charts (Apache-2.0, pinned 4.1.3 from unpkg) in an HTML component. Candles, volume,
MA10/20/50 and the plan's levels as price lines; drawing stays on the Chart page.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit.components.v1 as components

LIB = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"
MAS = {10: "#f2c94c", 20: "#f2994a", 50: "#9b51e0"}


def _series(bars: pd.DataFrame, column: str) -> list[dict]:
    return [
        {"time": str(d), "value": round(float(v), 4)}
        for d, v in zip(bars["time"], bars[column], strict=True)
        if v == v
    ]


def html(bars: pd.DataFrame, levels: dict[str, float], height: int, dark: bool = True) -> str:
    """The page for one chart. `bars`: session_date, open, high, low, close, volume (oldest
    first). `levels`: name -> price (entry, stop, pivot)."""
    b = bars.sort_values("session_date").copy()
    b["time"] = pd.to_datetime(b["session_date"]).dt.strftime("%Y-%m-%d")
    candles = [
        {"time": t, "open": float(o), "high": float(h), "low": float(lo), "close": float(c)}
        for t, o, h, lo, c in zip(b.time, b.open, b.high, b.low, b.close, strict=True)
    ]
    volume = [
        {"time": t, "value": float(v), "color": "#26a69a55" if c >= o else "#ef535055"}
        for t, v, o, c in zip(b.time, b.volume, b.open, b.close, strict=True)
    ]
    mas = {n: _series(b.assign(m=b["close"].rolling(n).mean()), "m") for n in MAS}
    bg, text, grid = ("#0e1117", "#d1d4dc", "#1e222d") if dark else ("#ffffff", "#131722", "#eee")
    colours = {"entry": "#2da44e", "pivot": "#2da44e", "stop": "#ef5350"}
    lines = [
        {"price": float(p), "title": k, "color": colours.get(k, "#8a8a8a")}
        for k, p in levels.items()
        if p is not None and p == p
    ]
    data = json.dumps(
        {"candles": candles, "volume": volume, "mas": mas, "lines": lines, "ma_colours": MAS}
    )
    return f"""<div id="c" style="width:100%;height:{height}px"></div>
<script src="{LIB}"></script>
<script>
const d = {data};
const el = document.getElementById('c');
const chart = LightweightCharts.createChart(el, {{
  autoSize: true,
  layout: {{background: {{color: '{bg}'}}, textColor: '{text}'}},
  grid: {{vertLines: {{color: '{grid}'}}, horzLines: {{color: '{grid}'}}}},
  rightPriceScale: {{scaleMargins: {{top: 0.08, bottom: 0.25}}}},
  timeScale: {{rightOffset: 5}},
  crosshair: {{mode: 0}},
}});
const s = chart.addCandlestickSeries({{upColor: '#26a69a', downColor: '#ef5350',
  borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350'}});
s.setData(d.candles);
const v = chart.addHistogramSeries({{priceFormat: {{type: 'volume'}}, priceScaleId: 'vol'}});
chart.priceScale('vol').applyOptions({{scaleMargins: {{top: 0.8, bottom: 0}}}});
v.setData(d.volume);
for (const [n, pts] of Object.entries(d.mas)) {{
  const l = chart.addLineSeries({{color: d.ma_colours[n], lineWidth: 1, priceLineVisible: false,
    lastValueVisible: false, crosshairMarkerVisible: false}});
  l.setData(pts);
}}
for (const p of d.lines) {{
  s.createPriceLine({{price: p.price, color: p.color, lineWidth: 1, lineStyle: 2,
    axisLabelVisible: true, title: p.title}});
}}
const n = d.candles.length;
chart.timeScale().setVisibleLogicalRange({{from: Math.max(0, n - 130), to: n + 3}});
</script>"""


def show(bars: pd.DataFrame, levels: dict[str, float], height: int = 520) -> None:
    components.html(html(bars, levels, height), height=height + 10)
