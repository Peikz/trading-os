// Today: the candidate board's Focus view (app/board.py). One candidate at a time: its chart
// (candles, volume, MA 10/20/50, entry and stop lines), its key stats, its card, and the queue.
// Flip with ◀ ▶ or the arrow keys; W switches daily/weekly bars.
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  DEFAULT_INDICATORS,
  INDICATORS,
  type Bars,
  type BoardRow,
  type Scope,
  type Today as TodayData,
} from "../api";
import { CandleChart } from "../components/CandleChart";
import { Card, KeyStats, Queue } from "../components/Card";
import { MarketTiles } from "../components/MarketTiles";

const SCOPES: { id: Scope; label: string }[] = [
  { id: "graded", label: "A+ / A / B" },
  { id: "pushed", label: "Pushed, incl. C" },
  { id: "all", label: "Every scan hit" },
];

/** The push link's stocks (`?t=A,B`), as the Streamlit board reads them. */
export function pushTickers(search: string): string[] {
  const t = new URLSearchParams(search).get("t") ?? "";
  return t
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

export function Today() {
  const fromPush = useMemo(() => pushTickers(window.location.search), []);
  const [scope, setScope] = useState<Scope>("graded");
  const [usePush, setUsePush] = useState(fromPush.length > 0);
  const [data, setData] = useState<TodayData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [tf, setTf] = useState<"1D" | "1W">("1D");
  const [picked, setPicked] = useState<string[]>(DEFAULT_INDICATORS);
  const [tab, setTab] = useState<"plan" | "list">("plan");

  useEffect(() => {
    setData(null);
    setError(null);
    api.today(scope, usePush ? fromPush : undefined).then(
      (d) => {
        setData(d);
        setIndex(0);
      },
      (e: Error) => setError(e.message),
    );
  }, [scope, usePush, fromPush]);

  const rows = data?.rows ?? [];
  const n = rows.length;
  const step = useCallback((by: number) => n && setIndex((i) => (i + by + n) % n), [n]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
      else if (e.key === "w" || e.key === "W") setTf((t) => (t === "1D" ? "1W" : "1D"));
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step]);

  const row: BoardRow | undefined = rows[Math.min(index, Math.max(0, n - 1))];

  return (
    <div>
      <MarketTiles />
      <div className="toolbar">
        <h2>Candidates</h2>
        <select
          aria-label="Show"
          value={usePush ? "push" : scope}
          onChange={(e) => {
            if (e.target.value === "push") return setUsePush(true);
            setUsePush(false);
            setScope(e.target.value as Scope);
          }}
        >
          {fromPush.length > 0 && <option value="push">From the push</option>}
          {SCOPES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && n === 0 && (
        <p className="muted">
          {data.total > 0
            ? "No A+ / A / B today. Pick 'Pushed, incl. C' or more in 'Show' for the rest."
            : "No signals in the latest runs."}
        </p>
      )}
      {row && (
        <>
          <nav className="flip" aria-label="Flip through">
            <button onClick={() => step(-1)} title="Previous (← key)">
              ◀
            </button>
            <span>
              {index + 1} of {n}
              {data && data.hidden_c > 0 && ` · ${data.hidden_c} C hidden`}
            </span>
            <button onClick={() => step(1)} title="Next (→ key)">
              ▶
            </button>
          </nav>
          <div className="pills" role="group" aria-label="Bars and indicators">
            {(["1D", "1W"] as const).map((t) => (
              <button key={t} className={tf === t ? "on" : ""} onClick={() => setTf(t)}>
                {t}
              </button>
            ))}
            <span className="sep" />
            {INDICATORS.map((name) => (
              <button
                key={name}
                className={picked.includes(name) ? "on" : ""}
                onClick={() =>
                  setPicked((p) => (p.includes(name) ? p.filter((x) => x !== name) : [...p, name]))
                }
              >
                {name}
              </button>
            ))}
          </div>
          <div className="focus">
            <div className="focus-main">
              <FocusChart row={row} tf={tf} picked={picked} />
              <KeyStats row={row} />
            </div>
            <aside className="focus-side">
              <div className="tabs" role="tablist">
                <button
                  role="tab"
                  aria-selected={tab === "plan"}
                  className={tab === "plan" ? "on" : ""}
                  onClick={() => setTab("plan")}
                >
                  Plan
                </button>
                <button
                  role="tab"
                  aria-selected={tab === "list"}
                  className={tab === "list" ? "on" : ""}
                  onClick={() => setTab("list")}
                >
                  List ({n})
                </button>
              </div>
              {tab === "plan" ? (
                <Card row={row} />
              ) : (
                <Queue
                  rows={rows}
                  index={index}
                  onPick={(i) => {
                    setIndex(i);
                    setTab("plan");
                  }}
                />
              )}
            </aside>
          </div>
        </>
      )}
    </div>
  );
}

function FocusChart({ row, tf, picked }: { row: BoardRow; tf: "1D" | "1W"; picked: string[] }) {
  const [bars, setBars] = useState<Bars | null>(null);
  const [error, setError] = useState<string | null>(null);
  const anchor = (row.avwap_anchor as string | null) ?? (row.run_session as string | null);
  const key = picked.join(",");

  useEffect(() => {
    let live = true;
    setError(null);
    api.bars(row.ticker, tf, key ? key.split(",") : [], anchor).then(
      (b) => live && setBars(b),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [row.ticker, tf, key, anchor]);

  if (error) return <p className="error">Chart: {error}</p>;
  if (!bars || bars.ticker !== row.ticker.toUpperCase()) {
    return <div className="chart muted">Loading the chart…</div>;
  }
  const where = row.exchange ? ` · ${row.exchange}` : "";
  return (
    <CandleChart
      bars={bars}
      levels={row.levels}
      title={`${row.ticker} · ${tf}${where}`}
      showBars={tf === "1D" ? 130 : 80}
    />
  );
}
