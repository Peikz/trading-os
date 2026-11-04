// The Journal's R curve: the cumulative R of closed trades by exit date (from the API), drawn
// with Lightweight Charts like the focus chart.
import { createChart, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { LAYOUT, T } from "./chartTheme";

export function RCurve({ points }: { points: { time: string; value: number }[] }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current || !points.length) return;
    const chart = createChart(box.current, {
      height: 200,
      autoSize: true,
      ...LAYOUT,
    });
    const line = chart.addLineSeries({ color: T.accent, lineWidth: 2 });
    // One point per day: the last cumulative R of that day
    const byDay = new Map(points.map((p) => [p.time.slice(0, 10), p.value]));
    line.setData([...byDay].map(([time, value]) => ({ time: time as Time, value })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [points]);
  return <div ref={box} className="chart" aria-label="R curve" style={{ height: 200 }} />;
}
