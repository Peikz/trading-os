// A stock's bars with your fills, for the Journal: around one trade (three months before the entry
// to six weeks after the exit, with the entry, exit and stop as lines), or the last months of a
// stock with the fills you have on it. Bars and fills come from /api/chart.
import { useEffect, useState } from "react";
import { api, type ChartData, type Level } from "../api";
import { DrawChart } from "./DrawChart";

const addDays = (day: string, n: number): string => {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

function useBars(ticker: string, period: string) {
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    api
      .chart(ticker, {
        period,
        timeframe: "Daily",
        span: "All",
        lines: ["MA10", "MA20", "MA50"],
        hits: false,
        fills: true,
        levels: false,
        anchors: [],
      })
      .then(
        (d) => live && setData(d),
        (e: Error) => live && setError(e.message),
      );
    return () => {
      live = false;
    };
  }, [ticker, period]);
  return { data, error };
}

/** The trade's chart: the stock's bars around the trade, with your fills as arrows. */
export function TradeChart({
  ticker,
  entry,
  exit,
  stop,
  height = 300,
}: {
  ticker: string;
  entry: string;
  exit: string;
  stop?: number | null;
  height?: number;
}) {
  const old = entry && Date.now() - Date.parse(entry) > 600 * 86400000; // beyond the 2-year file's reach
  const { data: raw, error } = useBars(ticker, old ? "10y" : "2y");
  if (error) return <p className="error">{error}</p>;
  if (!raw) return <p className="muted">Loading the chart…</p>;
  if (!raw.candles.length) return <p className="muted">No daily bars for {ticker} in the data repo.</p>;
  // Around the trade: three months before the entry to six weeks after the exit
  const days = raw.candles.map((c) => c.time);
  const from = days.find((t) => t >= addDays(entry, -90)) ?? days[0];
  // An open trade runs to the newest bar; a closed one to six weeks after the exit
  const to = exit ? ([...days].reverse().find((t) => t <= addDays(exit, 45)) ?? days[days.length - 1]) : days[days.length - 1];
  const levels: Level[] = stop ? [{ name: "stop", price: stop, colour: "#ef5350" }] : [];
  const data: ChartData = from && to ? { ...raw, visible: { from, to }, levels } : { ...raw, levels };
  return (
    <div className="trade-chart" aria-label={`${ticker} trade chart`}>
      <DrawChart data={data} height={height} tool="none" markerText={false} />
    </div>
  );
}

/** A stock's last months with your fills on it (the notebook's stock page). */
export function StockChart({ ticker, height = 300 }: { ticker: string; height?: number }) {
  const { data: raw, error } = useBars(ticker, "2y");
  if (error) return <p className="error">{error}</p>;
  if (!raw) return <p className="muted">Loading the chart…</p>;
  if (!raw.candles.length) return <p className="muted">No daily bars for {ticker} in the data repo.</p>;
  const days = raw.candles.map((c) => c.time);
  const data: ChartData = {
    ...raw,
    levels: [],
    visible: { from: days[Math.max(0, days.length - 150)], to: days[days.length - 1] },
  };
  return (
    <div className="trade-chart" aria-label={`${ticker} chart`}>
      <DrawChart data={data} height={height} tool="none" markerText={false} />
    </div>
  );
}
