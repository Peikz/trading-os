// The Chart page's chart: candles with volume, MA/EMA lines, anchored VWAPs, saved trend lines,
// scan-hit and fill markers and the price levels (all from /api/chart), drawn with TradingView's
// Lightweight Charts. On the daily bars three tools edit trend lines: ✏️ draw (two clicks; a
// click past the last bar makes it extend each day), ✋ move (drag a line's end) and 🧽 erase
// (click a line). The page saves each change at once through the API.
import {
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import type { ChartData, TrendLine } from "../api";
import { LAYOUT, lineLook, T } from "./chartTheme";

export type Tool = "none" | "draw" | "move" | "erase";
export interface Point {
  time: string;
  price: number;
}

interface Props {
  data: ChartData;
  height?: number;
  tool: Tool;
  onDraw?: (a: Point, b: Point, extend: boolean) => void;
  onMove?: (line: TrendLine, a: Point, b: Point) => void;
  onErase?: (line: TrendLine) => void;
}

const NEAR_PX = 9;

/** A Time from the chart as YYYY-MM-DD (strings come back as BusinessDay objects). */
export function dayOf(t: Time | undefined): string | null {
  if (t === undefined) return null;
  if (typeof t === "string") return t;
  if (typeof t === "number") return new Date(t * 1000).toISOString().slice(0, 10);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${t.year}-${pad(t.month)}-${pad(t.day)}`;
}

/** Distance in pixels from p to the segment a-b. */
export function toSegment(p: [number, number], a: [number, number], b: [number, number]): number {
  const [px, py] = p;
  const [ax, ay] = a;
  const [bx, by] = b;
  const dx = bx - ax;
  const dy = by - ay;
  const len = dx * dx + dy * dy;
  const k = len ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len)) : 0;
  return Math.hypot(px - (ax + k * dx), py - (ay + k * dy));
}

export function DrawChart({ data, height = 560, tool, onDraw, onMove, onErase }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const trend = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const first = useRef<Point | null>(null);
  const drag = useRef<{ line: TrendLine; end: 0 | 1; a: Point; b: Point } | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const props = useRef({ data, tool, onDraw, onMove, onErase });
  props.current = { data, tool, onDraw, onMove, onErase };

  // Build the chart once per data set
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      height,
      autoSize: true,
      ...LAYOUT,
      crosshair: { mode: CrosshairMode.Normal },
      
      timeScale: { borderColor: T.border, rightOffset: 8 },
    });
    chart.current = c;
    const price = c.addCandlestickSeries({
      upColor: T.up,
      downColor: T.down,
      borderVisible: false,
      wickUpColor: T.up,
      wickDownColor: T.down,
    });
    candles.current = price;
    price.setData(
      data.candles.map((k) => ({ time: k.time as Time, open: k.open, high: k.high, low: k.low, close: k.close })),
    );
    const vol = c.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" } });
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(
      data.candles.map((k) => ({
        time: k.time as Time,
        value: k.volume,
        color: k.close >= k.open ? T.upFade : T.downFade,
      })),
    );
    for (const l of data.lines) {
      const s = c.addLineSeries({ ...lineLook(l.name, l.colour), lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      s.setData(l.pts.map((p) => ({ time: p.time as Time, value: p.value })));
    }
    for (const l of data.avwaps) {
      const s = c.addLineSeries({
        color: l.colour,
        lineWidth: 2,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
        title: l.name,
      });
      s.setData(l.pts.map((p) => ({ time: p.time as Time, value: p.value })));
    }
    trend.current = new Map();
    for (const l of data.trend) {
      const s = c.addLineSeries({
        color: l.colour,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        title: l.label,
      });
      s.setData(l.pts.map((p) => ({ time: p.time as Time, value: p.value })));
      trend.current.set(l.id, s);
    }
    for (const lv of data.levels) {
      price.createPriceLine({
        price: lv.price,
        color: lv.colour,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: lv.name,
      });
    }
    price.setMarkers(data.markers.map((m) => ({ ...m, time: m.time as Time })) as SeriesMarker<Time>[]);
    if (data.visible) c.timeScale().setVisibleRange({ from: data.visible.from as Time, to: data.visible.to as Time });
    else c.timeScale().fitContent();
    return () => {
      c.remove();
      chart.current = null;
    };
  }, [data, height]);

  // The tools
  useEffect(() => {
    const c = chart.current;
    const el = box.current;
    if (!c || !el) return;
    first.current = null;
    setHint(
      tool === "draw" ? "Click the line's first point." : tool === "move" ? "Drag a line's end." : tool === "erase" ? "Click the line to delete." : null,
    );
    const locked = tool === "move";
    c.applyOptions({ handleScroll: !locked, handleScale: !locked });

    const at = (x: number, y: number): { point: Point; past: boolean } | null => {
      const series = candles.current;
      const bars = props.current.data.candles;
      if (!series || !bars.length) return null;
      const logical = c.timeScale().coordinateToLogical(x);
      const price = series.coordinateToPrice(y);
      if (logical === null || price === null) return null;
      const i = Math.round(logical);
      const k = Math.max(0, Math.min(bars.length - 1, i));
      return { point: { time: bars[k].time, price: Math.round(price * 100) / 100 }, past: i >= bars.length - 1 };
    };
    const pixel = (p: Point): [number, number] | null => {
      const x = c.timeScale().timeToCoordinate(p.time as Time);
      const y = candles.current?.priceToCoordinate(p.price);
      return x === null || y === null || y === undefined ? null : [x, y];
    };

    // A press and release within a few pixels is a click. The chart's own click event waits
    // out its double-click window and drops a second click inside it, which lost the line's
    // second point when you clicked quickly.
    const onClick = (x: number, y: number) => {
      const { tool: now, onDraw: draw, onErase: erase, data: d } = props.current;
      if (now === "draw") {
        const hit = at(x, y);
        if (!hit) return;
        if (!first.current) {
          first.current = hit.point;
          setHint(`First point ${hit.point.time} ${hit.point.price.toFixed(2)}: click the second.`);
        } else {
          const a = first.current;
          first.current = null;
          setHint("Click the line's first point.");
          if (a.time !== hit.point.time) draw?.(a, hit.point, hit.past);
        }
      } else if (now === "erase") {
        const p: [number, number] = [x, y];
        let best: { line: TrendLine; dist: number } | null = null;
        for (const l of d.trend) {
          const ends = [l.pts[0], l.pts[l.pts.length - 1]].map((x) => ({ time: x.time, price: x.value }));
          const a = pixel(ends[0]);
          const b = pixel(ends[1]);
          if (!a || !b) continue;
          const dist = toSegment(p, a, b);
          if (dist <= NEAR_PX && (!best || dist < best.dist)) best = { line: l, dist };
        }
        if (best) erase?.(best.line);
      }
    };

    const xy = (e: { clientX: number; clientY: number }): [number, number] => {
      const r = el.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    // Mouse and touch share these: a press, a drag (✋ moves a line's end) and a release (a
    // tap or click when it hardly moved). After a touch the browser may also send mouse
    // events for it, so mouse events right after a touch are ignored.
    let pressed: [number, number] | null = null;
    let lastTouch = 0;
    const press = (p: [number, number], prevent: () => void) => {
      pressed = p;
      if (props.current.tool !== "move") return;
      for (const l of props.current.data.trend) {
        const ends: Point[] = [
          { time: l.x0, price: l.y0 },
          { time: l.x1, price: l.y1 },
        ];
        for (const end of [0, 1] as const) {
          const q = pixel(ends[end]);
          if (q && Math.hypot(q[0] - p[0], q[1] - p[1]) <= NEAR_PX + 6) {
            drag.current = { line: l, end, a: ends[0], b: ends[1] };
            prevent();
            return;
          }
        }
      }
    };
    const drift = (p: [number, number]) => {
      const d = drag.current;
      if (!d) return;
      const hit = at(...p);
      if (!hit) return;
      if (d.end === 0) d.a = hit.point;
      else d.b = hit.point;
      trend.current.get(d.line.id)?.setData(
        [d.a, d.b]
          .sort((x, y) => (x.time < y.time ? -1 : 1))
          .map((q) => ({ time: q.time as Time, value: q.price })),
      );
    };
    const release = (p: [number, number]) => {
      const d = drag.current;
      drag.current = null;
      if (d) {
        if (d.a.time !== d.b.time) props.current.onMove?.(d.line, d.a, d.b);
        return;
      }
      const start = pressed;
      pressed = null;
      if (start && Math.hypot(p[0] - start[0], p[1] - start[1]) < 5) onClick(p[0], p[1]);
    };
    const fromTouch = () => Date.now() - lastTouch < 800;
    const down = (e: MouseEvent) => !fromTouch() && press(xy(e), () => e.preventDefault());
    const move = (e: MouseEvent) => !fromTouch() && drift(xy(e));
    const up = (e: MouseEvent) => !fromTouch() && release(xy(e));
    const tStart = (e: TouchEvent) => {
      lastTouch = Date.now();
      if (e.touches.length === 1) press(xy(e.touches[0]), () => e.preventDefault());
      else pressed = null; // a pinch is a zoom, not a tap
    };
    const tMove = (e: TouchEvent) => {
      lastTouch = Date.now();
      if (!drag.current) return;
      e.preventDefault(); // keep the page from scrolling while a line's end moves
      drift(xy(e.touches[0]));
    };
    const tEnd = (e: TouchEvent) => {
      lastTouch = Date.now();
      if (e.changedTouches.length) release(xy(e.changedTouches[0]));
    };
    el.addEventListener("mousedown", down, true);
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    el.addEventListener("touchstart", tStart, { capture: true, passive: false });
    el.addEventListener("touchmove", tMove, { capture: true, passive: false });
    el.addEventListener("touchend", tEnd, true);
    return () => {
      el.removeEventListener("mousedown", down, true);
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      el.removeEventListener("touchstart", tStart, true);
      el.removeEventListener("touchmove", tMove, true);
      el.removeEventListener("touchend", tEnd, true);
    };
  }, [tool, data]);

  return (
    <div>
      <div ref={box} className={`chart tool-${tool}`} style={{ height }} aria-label="Chart" />
      {hint && <p className="muted hint">{hint}</p>}
    </div>
  );
}
