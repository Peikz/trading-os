// The Screener's preview panel (desktop): the selected row's ticker, grade, last and change, a
// candle chart with the plan's entry and stop lines, Entry / Stop / Risk tiles, the why line,
// "Open on Chart" and "Watch". Up / Down move the selection and Enter opens the Chart (Screener.tsx).
import { useEffect, useState } from "react";
import { api, type Spark } from "../../api";
import { GradeBadge } from "../../components/Card";
import { MiniCandles } from "../../components/MiniCandles";
import { nameOf } from "../../shell/symbols";
import { GREEN } from "../today/WatchNote";

export type Rec = Record<string, unknown>;
const n = (v: unknown): number | null => (typeof v === "number" && !Number.isNaN(v) ? v : null);
const money = (v: number | null) => (v === null ? "–" : v.toFixed(2));

export function Preview({ rec, source, onOpen }: { rec: Rec | null; source: string; onOpen: () => void }) {
  const ticker = rec ? String(rec.ticker) : "";
  const [bars, setBars] = useState<{ t: string; c: Spark } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    setMsg(null);
    if (!ticker) return;
    let live = true;
    api.sparks([ticker], 60).then(
      (s) => live && setBars({ t: ticker, c: s[ticker] ?? [] }),
      () => live && setBars({ t: ticker, c: [] }),
    );
    return () => {
      live = false;
    };
  }, [ticker]);
  if (!rec) {
    return (
      <aside className="preview" aria-label="Preview">
        <p className="muted">Pick a row to see it here.</p>
      </aside>
    );
  }
  const levels = (rec.levels as Record<string, number> | undefined) ?? {};
  const entry = n(rec.plan_entry) ?? levels.entry ?? null;
  const stop = n(rec.plan_stop) ?? levels.stop ?? null;
  const risk = entry !== null && stop !== null && entry > 0 ? ((entry - stop) / entry) * 100 : null;
  const chg = n(rec.chg_pct);
  const grade = typeof rec.grade === "string" ? rec.grade : "";
  const why = typeof rec.grade_why === "string" ? rec.grade_why : "";
  const company = nameOf(ticker);
  const lines: Record<string, number> = {};
  if (entry !== null) lines.entry = entry;
  if (stop !== null) lines.stop = stop;
  const watch = () =>
    api.flag(ticker, GREEN).then(
      () => setMsg(`${ticker} is on your watchlist`),
      (e: Error) => setMsg(`Error: ${e.message}`),
    );
  return (
    <aside className="preview" aria-label="Preview">
      <div className="pv-head">
        <span className="pv-tk">{ticker}</span>
        {grade && <GradeBadge grade={grade} />}
        <span className="grow" />
        <span className="num pv-last">{money(n(rec.close))}</span>
        <span className={`num ${chg === null ? "" : chg >= 0 ? "up" : "down"}`}>{chg === null ? "" : `${chg >= 0 ? "+" : ""}${chg.toFixed(1)}%`}</span>
      </div>
      <div className="muted pv-sub">
        {[company, typeof rec.scan_label === "string" ? rec.scan_label : "", n(rec.rvol50) !== null ? `RVOL ${n(rec.rvol50)!.toFixed(1)}` : "", n(rec.adr20_pct) !== null ? `ADR ${n(rec.adr20_pct)!.toFixed(1)}%` : ""]
          .filter(Boolean)
          .join(" · ")}
      </div>
      <div className="pv-chart">
        {bars && bars.t === ticker ? <MiniCandles candles={bars.c} levels={lines} height={200} label={ticker} /> : <div style={{ height: 200 }} />}
      </div>
      <div className="pv-tiles">
        <div>
          <span>Entry</span>
          <b className="num">{money(entry)}</b>
        </div>
        <div>
          <span>Stop</span>
          <b className="num">{money(stop)}</b>
        </div>
        <div>
          <span>Risk</span>
          <b className="num">{risk === null ? "–" : `${risk.toFixed(1)}%`}</b>
        </div>
      </div>
      <p className="muted pv-why">{why ? `Why: ${why}` : source}</p>
      <div className="pv-actions">
        <button className="primary" onClick={onOpen}>
          Open on Chart
        </button>
        <button onClick={watch}>★ Watch</button>
      </div>
      {msg && <p className="muted" role="status">{msg}</p>}
      <p className="muted hint">↑ ↓ move through the list · Enter opens on Chart</p>
    </aside>
  );
}
