// The focus chart: TradingView's Lightweight Charts (Apache-2.0). Candles, volume in its own
// band, the picked indicator lines, the plan's levels as labelled price lines (Entry, Stop,
// Pivot), and a legend top left (O H L C and each indicator's value) following the crosshair.
// Colours: the calm palette (chartTheme).
import {
  type AutoscaleInfo,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import type { Bars } from "../api";
import { LAYOUT, LEVELS, lineLook, T } from "./chartTheme";

interface Props {
  bars: Bars;
  levels: Record<string, number>;
  title: string;
  height?: number;
  showBars?: number;
}

interface Legend {
  o?: number;
  h?: number;
  l?: number;
  c?: number;
  chg?: number;
  values: { name: string; colour: string; value?: number }[];
}

function legendAt(bars: Bars, time: string | undefined): Legend {
  const i = time ? bars.candles.findIndex((c) => c.time === time) : bars.candles.length - 1;
  const bar = bars.candles[i];
  const prev = i > 0 ? bars.candles[i - 1] : undefined;
  const at = bar?.time;
  return {
    o: bar?.open,
    h: bar?.high,
    l: bar?.low,
    c: bar?.close,
    chg: bar && prev ? (bar.close / prev.close - 1) * 100 : undefined,
    values: bars.lines.map((line) => ({
      name: line.name,
      colour: lineLook(line.name, line.colour).color,
      value: line.pts.find((p) => p.time === at)?.value,
    })),
  };
}

const fmt = (v?: number) => (v === undefined ? "–" : v.toFixed(2));

export function CandleChart({ bars, levels, title, height = 520, showBars = 130 }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [legend, setLegend] = useState<Legend>(() => legendAt(bars, undefined));

  useEffect(() => {
    setLegend(legendAt(bars, undefined));
    const el = box.current;
    if (!el || bars.candles.length === 0) return;
    const chart: IChartApi = createChart(el, {
      height,
      autoSize: true,
      ...LAYOUT,
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: T.border, scaleMargins: { top: 0.08, bottom: 0.25 } },
    });
    const candles: ISeriesApi<"Candlestick"> = chart.addCandlestickSeries({
      upColor: T.up,
      downColor: T.down,
      borderVisible: false,
      wickUpColor: T.up,
      wickDownColor: T.down,
      // Keep the plan's entry and stop in view even when the price is far from them
      autoscaleInfoProvider: (base: () => AutoscaleInfo | null) => {
        const info = base();
        const prices = Object.values(levels);
        if (!info?.priceRange || prices.length === 0) return info;
        return {
          ...info,
          priceRange: {
            minValue: Math.min(info.priceRange.minValue, ...prices),
            maxValue: Math.max(info.priceRange.maxValue, ...prices),
          },
        };
      },
    });
    candles.setData(
      bars.candles.map((c) => ({
        time: c.time as Time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );
    const volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol" });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volume.setData(
      bars.candles.map((c) => ({
        time: c.time as Time,
        value: c.volume,
        color: c.close >= c.open ? T.upFade : T.downFade,
      })),
    );
    const hasRs = bars.lines.some((l) => l.scale === "rs");
    if (hasRs) {
      chart.priceScale("rs").applyOptions({ scaleMargins: { top: 0.62, bottom: 0.22 } });
    }
    for (const line of bars.lines) {
      const s = chart.addLineSeries({
        ...lineLook(line.name, line.colour),
        lineWidth: line.name === "MA 10" ? 2 : 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        ...(line.scale === "rs" ? { priceScaleId: "rs" } : {}),
      });
      s.setData(line.pts.map((p) => ({ time: p.time as Time, value: p.value })));
    }
    for (const [name, price] of Object.entries(levels)) {
      const [label, colour] = LEVELS[name] ?? [name, T.neutral];
      candles.createPriceLine({
        price,
        color: colour,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: label,
      });
    }
    const n = bars.candles.length;
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - showBars), to: n + 3 });
    const onMove = (p: MouseEventParams) => setLegend(legendAt(bars, p.time as string | undefined));
    chart.subscribeCrosshairMove(onMove);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
    };
  }, [bars, levels, height, showBars]);

  if (bars.candles.length === 0) {
    return (
      <div className="chart quiet" style={{ height, minHeight: 0 }}>
        <p className="muted">No daily bars for {bars.ticker} in the data repo yet.</p>
      </div>
    );
  }
  return (
    <div className="chart" style={{ height }}>
      <div className="chart-legend">
        <div>
          {title && <b>{title} </b>}
          <span className="ohlc">
            {" "}
            O {fmt(legend.o)} H {fmt(legend.h)} L {fmt(legend.l)} C {fmt(legend.c)}
            {legend.chg !== undefined && (
              <span style={{ color: legend.chg >= 0 ? "var(--up)" : "var(--down)" }}>
                {" "}
                {legend.chg >= 0 ? "+" : ""}
                {legend.chg.toFixed(2)}%
              </span>
            )}
          </span>
        </div>
        {legend.values.map((v) => (
          <div key={v.name} style={{ color: v.colour }}>
            {v.name} {fmt(v.value)}
          </div>
        ))}
      </div>
      <div ref={box} style={{ position: "absolute", inset: 0 }} data-testid="chart-canvas" />
    </div>
  );
}
