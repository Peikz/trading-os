// One day's minute candles (/api/chart/{t}/intraday): VWAP from the 09:30 open, volume, the
// prior close and your levels. Pre- and post-market candles are drawn faded. Times are New York
// wall-clock (the API shifts them), so the axis reads New York.
import { LineStyle, createChart, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Intraday } from "../api";
import { LAYOUT, T } from "./chartTheme";

export function IntradayChart({ data, height = 460 }: { data: Intraday; height?: number }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current || !data.candles.length) return;
    const c = createChart(box.current, {
      height,
      autoSize: true,
      ...LAYOUT,
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: T.border },
    });
    const price = c.addCandlestickSeries({ borderVisible: false });
    price.setData(
      data.candles.map((k) => {
        const up = k.close >= k.open;
        const colour = k.extended ? (up ? T.upFade : T.downFade) : up ? T.up : T.down;
        return {
          time: k.time as Time,
          open: k.open,
          high: k.high,
          low: k.low,
          close: k.close,
          color: colour,
          wickColor: colour,
        };
      }),
    );
    const vwap = c.addLineSeries({ color: "#8fb5ff", lineWidth: 2, title: "VWAP", priceLineVisible: false });
    vwap.setData(data.vwap.map((p) => ({ time: p.time as Time, value: p.value })));
    const vol = c.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" } });
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(data.candles.map((k) => ({ time: k.time as Time, value: k.volume, color: "#98a2b355" })));
    for (const lv of data.levels) {
      price.createPriceLine({ price: lv.price, color: lv.colour, lineStyle: LineStyle.Dashed, lineWidth: 1, title: lv.name, axisLabelVisible: true });
    }
    if (data.markers?.length) {
      price.setMarkers(data.markers.map((m) => ({ ...m, time: m.time as Time })));
    }
    c.timeScale().fitContent();
    return () => c.remove();
  }, [data, height]);
  if (!data.candles.length) return <p className="muted">No minute bars for this day.</p>;
  return <div ref={box} className="chart" style={{ height }} aria-label="Intraday chart" />;
}
