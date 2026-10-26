"""A fast chart for the focus view (Emil, 26 Oct 2026): TradingView's open-source Lightweight
Charts (Apache-2.0, pinned 4.1.3 from unpkg) in an iframe. Candles and volume on daily or weekly
bars; the indicators the user picks (MA / EMA lines, an anchored VWAP from the signal day, an RS
line against QQQ in its own band); the plan's levels as price lines; top left a TradingView-style
legend (ticker · timeframe · exchange, O H L C and change, each indicator's value) that follows
the crosshair. Drawing stays on the Chart page.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

LIB = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"
INDICATORS = {  # name -> (kind, length, colour)
    "MA 10": ("sma", 10, "#f2c94c"),
    "MA 20": ("sma", 20, "#f2994a"),
    "MA 50": ("sma", 50, "#9b51e0"),
    "MA 200": ("sma", 200, "#56ccf2"),
    "EMA 9": ("ema", 9, "#27ae60"),
    "EMA 21": ("ema", 21, "#eb5757"),
    "AVWAP (signal day)": ("avwap", 0, "#e0e0e0"),
    "RS vs QQQ": ("rs", 0, "#2f80ed"),
}
DEFAULT = ["MA 10", "MA 20", "MA 50"]


def weekly(bars: pd.DataFrame) -> pd.DataFrame:
    """Daily bars to weekly (the week's first open, high, low, last close, summed volume),
    dated by the week's first session."""
    b = bars.sort_values("session_date").copy()
    d = pd.to_datetime(b["session_date"])
    b["wk"] = d - pd.to_timedelta(d.dt.weekday, unit="D")
    w = b.groupby("wk").agg(
        session_date=("session_date", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return w.reset_index(drop=True)


def _points(times: pd.Series, values: pd.Series) -> list[dict]:
    return [
        {"time": t, "value": round(float(v), 4)}
        for t, v in zip(times, values, strict=True)
        if v is not None and v == v
    ]


def indicator_lines(
    b: pd.DataFrame, picked: list[str], anchor=None, bench: pd.DataFrame | None = None
) -> list[dict]:
    """The picked indicators as line series: name, colour, scale ('right' or 'rs'), points."""
    out = []
    for name in picked:
        kind, n, colour = INDICATORS[name]
        if kind == "sma":
            values = b["close"].rolling(n).mean()
        elif kind == "ema":
            values = b["close"].ewm(span=n, adjust=False).mean()
        elif kind == "avwap":
            if anchor is None:
                continue
            on = pd.to_datetime(b["session_date"]) >= pd.Timestamp(anchor)
            tp = (b["high"] + b["low"] + b["close"]) / 3
            values = (tp * b["volume"]).where(on).cumsum() / b["volume"].where(on).cumsum()
        elif kind == "rs":
            if bench is None or bench.empty:
                continue
            q = bench.drop_duplicates("session_date").set_index(
                pd.to_datetime(bench.drop_duplicates("session_date")["session_date"])
            )["close"]
            q_on = q.reindex(pd.to_datetime(b["session_date"])).to_numpy()
            values = pd.Series(b["close"].to_numpy() / q_on, index=b.index)
        else:
            continue
        scale = "rs" if kind == "rs" else "right"
        out.append(
            {"name": name, "colour": colour, "scale": scale, "pts": _points(b["time"], values)}
        )
    return out


def html(
    bars: pd.DataFrame,
    levels: dict[str, float],
    height: int,
    dark: bool = True,
    title: str = "",
    picked: list[str] | None = None,
    anchor=None,
    bench: pd.DataFrame | None = None,
    show_bars: int = 130,
) -> str:
    """The page for one chart. `bars`: session_date, open, high, low, close, volume (oldest
    first, daily or weekly). `levels`: name -> price. `picked`: indicator names (INDICATORS)."""
    b = bars.sort_values("session_date").reset_index(drop=True).copy()
    b["time"] = pd.to_datetime(b["session_date"]).dt.strftime("%Y-%m-%d")
    candles = [
        {"time": t, "open": float(o), "high": float(h), "low": float(lo), "close": float(c)}
        for t, o, h, lo, c in zip(b.time, b.open, b.high, b.low, b.close, strict=True)
    ]
    volume = [
        {"time": t, "value": float(v), "color": "#26a69a55" if c >= o else "#ef535055"}
        for t, v, o, c in zip(b.time, b.volume, b.open, b.close, strict=True)
    ]
    lines = indicator_lines(b, DEFAULT if picked is None else picked, anchor, bench)
    bg, text, grid = ("#0e1117", "#d1d4dc", "#1e222d") if dark else ("#ffffff", "#131722", "#eee")
    colours = {"entry": "#2da44e", "pivot": "#2da44e", "stop": "#ef5350"}
    levels_out = [
        {"price": float(p), "title": k, "color": colours.get(k, "#8a8a8a")}
        for k, p in levels.items()
        if p is not None and p == p
    ]
    data = json.dumps(
        {
            "candles": candles,
            "volume": volume,
            "lines": lines,
            "levels": levels_out,
            "title": title,
            "show": show_bars,
        }
    )
    return f"""<div style="position:relative;width:100%;height:{height}px">
<div id="c" style="width:100%;height:{height}px"></div>
<div id="lg" style="position:absolute;left:8px;top:6px;z-index:5;pointer-events:none;
  font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:{text};line-height:1.55"></div>
</div>
<script src="{LIB}"></script>
<script>
const d = {data};
const el = document.getElementById('c');
const hasRs = d.lines.some(l => l.scale === 'rs');
const chart = LightweightCharts.createChart(el, {{
  autoSize: true,
  layout: {{background: {{color: '{bg}'}}, textColor: '{text}'}},
  grid: {{vertLines: {{color: '{grid}'}}, horzLines: {{color: '{grid}'}}}},
  rightPriceScale: {{scaleMargins: {{top: 0.08, bottom: hasRs ? 0.38 : 0.25}}}},
  timeScale: {{rightOffset: 5}},
  crosshair: {{mode: 0}},
}});
const s = chart.addCandlestickSeries({{upColor: '#26a69a', downColor: '#ef5350',
  borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350'}});
s.setData(d.candles);
const v = chart.addHistogramSeries({{priceFormat: {{type: 'volume'}}, priceScaleId: 'vol'}});
chart.priceScale('vol').applyOptions({{scaleMargins: {{top: 0.84, bottom: 0}}}});
v.setData(d.volume);
const at = {{}};
for (const l of d.lines) {{
  const opts = {{color: l.colour, lineWidth: l.scale === 'rs' ? 2 : 1, priceLineVisible: false,
    lastValueVisible: false, crosshairMarkerVisible: false}};
  if (l.scale === 'rs') opts.priceScaleId = 'rs';
  const series = chart.addLineSeries(opts);
  series.setData(l.pts);
  at[l.name] = {{}}; l.pts.forEach(p => {{ at[l.name][p.time] = p.value; }});
}}
if (hasRs) chart.priceScale('rs').applyOptions({{scaleMargins: {{top: 0.66, bottom: 0.18}}}});
for (const p of d.levels) {{
  s.createPriceLine({{price: p.price, color: p.color, lineWidth: 1, lineStyle: 2,
    axisLabelVisible: true, title: p.title}});
}}
const n = d.candles.length;
chart.timeScale().setVisibleLogicalRange({{from: Math.max(0, n - d.show), to: n + 3}});
const byTime = {{}};
d.candles.forEach((c, i) => {{ byTime[c.time] = i; }});
const fmt = x => x == null ? '–' : x.toFixed(2);
const vol = x => x >= 1e6 ? (x / 1e6).toFixed(2) + 'M' : x >= 1e3 ? (x / 1e3).toFixed(0) + 'K' : x;
function legend(i) {{
  const c = d.candles[i], prev = d.candles[i - 1];
  const chg = prev ? (c.close / prev.close - 1) * 100 : 0;
  const col = c.close >= c.open ? '#26a69a' : '#ef5350';
  let h = `<b style="font-size:14px">${{d.title}}</b> &nbsp;` +
    `<span style="color:${{col}}">O ${{fmt(c.open)}} H ${{fmt(c.high)}} L ${{fmt(c.low)}} ` +
    `C ${{fmt(c.close)}} ${{chg >= 0 ? '+' : ''}}${{chg.toFixed(2)}}%</span>`;
  for (const l of d.lines) {{
    const val = l.scale === 'rs' ? '' : ' ' + fmt(at[l.name][c.time]);
    h += `<br><span style="color:${{l.colour}}">${{l.name}}${{val}}</span>`;
  }}
  h += `<br><span style="opacity:.8">Vol ${{vol(d.volume[i].value)}}</span>`;
  document.getElementById('lg').innerHTML = h;
}}
legend(n - 1);
chart.subscribeCrosshairMove(p => {{
  const i = p && p.time !== undefined ? byTime[p.time] : undefined;
  legend(i === undefined ? n - 1 : i);
}});
</script>"""


def show(bars: pd.DataFrame, levels: dict[str, float], height: int = 520, **kw) -> None:
    # Our own page from our own bars (st.iframe; components.html is deprecated)
    st.iframe(html(bars, levels, height, **kw), height=height + 10)
