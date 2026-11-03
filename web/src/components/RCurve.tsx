// The Journal's R curve: the cumulative R of closed trades by exit date (from the API), drawn
// with Lightweight Charts like the focus chart.
import { ColorType, createChart, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";

export function RCurve({ points }: { points: { time: string; value: number }[] }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current || !points.length) return;
    const chart = createChart(box.current, {
      height: 200,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0e1117" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#1f242c" }, horzLines: { color: "#1f242c" } },
    });
    const line = chart.addLineSeries({ color: "#2f81f7", lineWidth: 2 });
    // One point per day: the last cumulative R of that day
    const byDay = new Map(points.map((p) => [p.time.slice(0, 10), p.value]));
    line.setData([...byDay].map(([time, value]) => ({ time: time as Time, value })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [points]);
  return <div ref={box} className="chart" aria-label="R curve" style={{ height: 200 }} />;
}
