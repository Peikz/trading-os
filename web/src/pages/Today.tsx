// Today: the candidate board (app/board.py). Three views: Focus (one candidate: its chart, key
// stats, card with the Saxo ticket, the queue, Notes & alerts), Grid (four charts, the arrows
// page by four) and List (every card). Show: A+ / A / B, pushed incl. C, every scan hit, your
// watchlists, or a push link's / a screen's stocks. Hotkeys: ← → flip, W 1D/1W, F flags green,
// N jumps to the note, T shows or hides the ticket.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
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
import { FLAGS, NotesAlerts } from "../components/NotesAlerts";
import { Ticket } from "../components/Ticket";

const SCOPES: { id: Scope; label: string }[] = [
  { id: "graded", label: "A+ / A / B" },
  { id: "pushed", label: "Pushed, incl. C" },
  { id: "all", label: "Every scan hit" },
  { id: "watchlists", label: "My watchlists" },
];
type View = "Focus" | "Grid" | "List";
type Tab = "plan" | "list" | "notes";
const GREEN = FLAGS[2][1];
const NO_WATCHLISTS =
  "No stocks in your watchlists yet: flag one here (F, or 🟥 🟨 🟩 under Notes & alerts) or " +
  "add lists on the Watchlists page (also from a TradingView export).";

/** The push link's stocks (`?t=A,B`), as the Streamlit board reads them. */
export function pushTickers(search: string): string[] {
  const t = new URLSearchParams(search).get("t") ?? "";
  return t
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

/** The screen a Screener "Flip through on Today" link came from (`?screen=Name&t=A,B`). */
export function screenName(search: string): string | null {
  return new URLSearchParams(search).get("screen") || null;
}

export function Today() {
  const fromPush = useMemo(() => pushTickers(window.location.search), []);
  const screen = useMemo(() => screenName(window.location.search), []);
  const pinned = screen ? `From the screen: ${screen}` : "From the push";
  const [scope, setScope] = useState<Scope>("graded");
  const [usePush, setUsePush] = useState(fromPush.length > 0);
  const [data, setData] = useState<TodayData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [view, setView] = useState<View>("Focus");
  const [tf, setTf] = useState<"1D" | "1W">("1D");
  const [picked, setPicked] = useState<string[]>(DEFAULT_INDICATORS);
  const [tab, setTab] = useState<Tab>("plan");
  const [showTicket, setShowTicket] = useState(true);
  const [flash, setFlash] = useState<string | null>(null);
  const [focusNote, setFocusNote] = useState(0);
  const noteRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    const call = usePush ? api.today("all", fromPush, screen) : api.today(scope);
    call.then(
      (d) => {
        setData(d);
        setIndex(0);
      },
      (e: Error) => setError(e.message),
    );
  }, [scope, usePush, fromPush, screen]);

  useEffect(() => {
    if (!flash) return;
    const timer = setTimeout(() => setFlash(null), 4000);
    return () => clearTimeout(timer);
  }, [flash]);

  // N: the Notes tab, then the note box once it is shown
  useEffect(() => {
    if (focusNote) noteRef.current?.focus();
  }, [focusNote, tab]);

  const rows = useMemo(() => data?.rows ?? [], [data]);
  const n = rows.length;
  const pages = view === "Grid" ? Math.ceil(n / 4) : n;
  const step = useCallback(
    (by: number) => pages && setIndex((i) => (i + by + pages) % pages),
    [pages],
  );
  const current = Math.min(index, Math.max(0, pages - 1));
  const row: BoardRow | undefined = view === "Focus" ? rows[current] : undefined;

  // A layout effect: the listener is current as soon as a new queue is on screen (a passive
  // effect left a moment where an arrow key still saw the old, empty queue).
  useLayoutEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const key = e.key.toLowerCase();
      if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
      else if (key === "w") setTf((t) => (t === "1D" ? "1W" : "1D"));
      else if (key === "f" && row) {
        api.flag(row.ticker, GREEN).then(
          (r) => setFlash(r.message),
          (err: Error) => setFlash(`❌ ${err.message}`),
        );
      } else if (key === "n" && row) {
        setTab("notes");
        setFocusNote((k) => k + 1);
      } else if (key === "t" && row) {
        setTab("plan");
        setShowTicket((s) => !s);
      } else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, row]);

  const hidden = data && data.hidden_c > 0 ? ` · ${data.hidden_c} C hidden` : "";
  const where =
    view === "Grid"
      ? `${current * 4 + 1}-${Math.min(current * 4 + 4, n)} of ${n}${hidden}`
      : `${current + 1} of ${n}${hidden}`;

  return (
    <div>
      <MarketTiles />
      <div className="toolbar">
        <h2>Candidates</h2>
        <div className="pills" role="group" aria-label="View">
          {(["Focus", "Grid", "List"] as const).map((v) => (
            <button
              key={v}
              className={view === v ? "on" : ""}
              onClick={() => {
                setView(v);
                setIndex(0);
              }}
            >
              {v}
            </button>
          ))}
        </div>
        <select
          aria-label="Show"
          value={usePush ? "push" : scope}
          onChange={(e) => {
            if (e.target.value === "push") return setUsePush(true);
            setUsePush(false);
            setScope(e.target.value as Scope);
          }}
        >
          {fromPush.length > 0 && <option value="push">{pinned}</option>}
          {SCOPES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        {usePush && !screen && (
          <button
            title="Every scan's hits, the C strategies too"
            onClick={() => {
              setUsePush(false);
              setScope("all");
            }}
          >
            Show everything this run found
          </button>
        )}
      </div>
      {flash && (
        <p className="flash" role="status">
          {flash}
        </p>
      )}
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && n === 0 && (
        <p className="muted">
          {scope === "watchlists" && !usePush
            ? NO_WATCHLISTS
            : data.total > 0
              ? "No A+ / A / B today. Pick 'Pushed, incl. C' or more in 'Show' for the rest."
              : "No signals in the latest runs."}
        </p>
      )}
      {n > 0 && view === "List" && (
        <>
          <p className="muted">
            {n} signals{hidden}
          </p>
          <div className="cards">
            {rows.map((r) => (
              <ListCard key={`${r.ticker}-${r.scan}`} row={r} />
            ))}
          </div>
        </>
      )}
      {n > 0 && view !== "List" && (
        <>
          <nav className="flip" aria-label="Flip through">
            <button onClick={() => step(-1)} title="Previous (← key)">
              ◀
            </button>
            <span>{where}</span>
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
        </>
      )}
      {n > 0 && view === "Grid" && (
        <div className="grid" aria-label="Grid">
          {rows.slice(current * 4, current * 4 + 4).map((r) => (
            <div key={`${r.ticker}-${r.scan}`}>
              <b>
                {r.grade} · {r.ticker}
              </b>{" "}
              · {r.scan_label}
              <FocusChart row={r} tf={tf} picked={picked} height={330} />
              <KeyStats row={r} />
            </div>
          ))}
        </div>
      )}
      {row && (
        <div className="focus">
          <div className="focus-main">
            <FocusChart row={row} tf={tf} picked={picked} />
            <KeyStats row={row} />
            <p className="muted hotkeys">
              Keys: ← → flip · W 1D/1W · F 🟩 flag · N note · T ticket
            </p>
          </div>
          <aside className="focus-side">
            <div className="tabs" role="tablist">
              {(
                [
                  ["plan", "Plan"],
                  ["list", `List (${n})`],
                  ["notes", "Notes & alerts"],
                ] as [Tab, string][]
              ).map(([id, label]) => (
                <button
                  key={id}
                  role="tab"
                  aria-selected={tab === id}
                  className={tab === id ? "on" : ""}
                  onClick={() => setTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            {tab === "plan" && (
              <>
                <Card row={row} />
                {showTicket ? (
                  <>
                    <h3>🎫 Saxo ticket</h3>
                    <Ticket row={row} />
                  </>
                ) : (
                  <p className="muted">Ticket hidden (T shows it).</p>
                )}
              </>
            )}
            {tab === "list" && (
              <Queue
                rows={rows}
                index={current}
                onPick={(i) => {
                  setIndex(i);
                  setTab("plan");
                }}
              />
            )}
            {tab === "notes" && <NotesAlerts row={row} noteRef={noteRef} onMessage={setFlash} />}
          </aside>
        </div>
      )}
    </div>
  );
}

function ListCard({ row }: { row: BoardRow }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <Card row={row} />
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        🎫 Saxo ticket
      </button>
      {open && <Ticket row={row} />}
    </div>
  );
}

function FocusChart({
  row,
  tf,
  picked,
  height,
}: {
  row: BoardRow;
  tf: "1D" | "1W";
  picked: string[];
  height?: number;
}) {
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
      height={height}
      showBars={tf === "1D" ? 130 : 80}
    />
  );
}
