// Today: "What do I do today?" (design review 4 Nov 2026). Left, the queue in three parts: TO ACT
// ON (A+ / A / B), YOUR POSITIONS and WATCHING (Flag green). Centre, the chart and a quiet strip
// of key facts. Right, the plan card that leads with the decision, why the grade, then Watch and
// a note. Arrow keys flip the queue, W watches, N writes a note. A quiet day (no A+ / A / B)
// shows a calm "Nothing to buy today" with the way on: the C setups, your watchlist and the next
// scan. A push link (`?t=A,B`) or a screen's flip link puts those stocks first. On a phone, one
// card per stock, flipped with prev / next and dots.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type BoardRow,
  DEFAULT_INDICATORS,
  type NextScan,
  type PositionCard,
  type Positions,
  type Spark,
  type Stat,
  type Timeframe,
} from "../api";
import { FactStrip, GradeBadge, KindBadge } from "../components/Card";
import { MiniCandles } from "../components/MiniCandles";
import { signed, usd } from "../format";
import { stripIcons } from "../plain";
import { hrefFor, stockLink } from "../routes";
import { Icon } from "../ui/Icon";
import { PHONE, typing, useMedia } from "../ui/kit";
import { FocusChart } from "./today/FocusChart";
import { CopyOrder, Numbers, PlanCard, useTicket, WhyCard } from "./today/PlanCard";
import { GREEN, WatchButton, WatchNote } from "./today/WatchNote";

/** The push link's stocks (`?t=A,B`), as the Streamlit board reads them. */
export function pushTickers(search: string): string[] {
  const t = new URLSearchParams(search).get("t") ?? "";
  return t
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

/** The screen a "Flip through on Today" link came from (`?screen=Name&t=A,B`). */
export function screenName(search: string): string | null {
  return new URLSearchParams(search).get("screen") || null;
}

type Kind = "push" | "act" | "c" | "position" | "watch";
interface Item {
  key: string;
  kind: Kind;
  ticker: string;
  row?: BoardRow;
  pos?: PositionCard;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** "2 setups to act on · 1 position · 2 on watch" */
export function titleLine(act: number, positions: number, watch: number): string {
  return [
    act ? `${plural(act, "setup")} to act on` : "Nothing to act on",
    plural(positions, "position"),
    `${watch} on watch`,
  ].join(" · ");
}

function rowItem(kind: Kind, r: BoardRow): Item {
  return { key: `${kind}:${r.ticker}:${r.scan}`, kind, ticker: r.ticker, row: r };
}

function useToday() {
  const fromPush = useMemo(() => pushTickers(window.location.search), []);
  const screen = useMemo(() => screenName(window.location.search), []);
  const [act, setAct] = useState<BoardRow[] | null>(null);
  const [hiddenC, setHiddenC] = useState(0);
  const [next, setNext] = useState<NextScan | null>(null);
  const [push, setPush] = useState<BoardRow[]>([]);
  const [cRows, setCRows] = useState<BoardRow[] | null>(null);
  const [positions, setPositions] = useState<Positions | null>(null);
  const [watch, setWatch] = useState<BoardRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadWatch = useCallback(
    () => api.today("watchlists", [], null, GREEN).then((d) => setWatch(d.rows), () => setWatch([])),
    [],
  );
  useEffect(() => {
    api.today("graded").then(
      (d) => {
        setAct(d.rows);
        setHiddenC(d.hidden_c);
        setNext(d.next_scan ?? null);
      },
      (e: Error) => {
        setAct([]);
        setError(e.message);
      },
    );
    if (fromPush.length) api.today("all", fromPush, screen).then((d) => setPush(d.rows), () => setPush([]));
    api.positions().then(setPositions, () => setPositions(null));
    loadWatch();
  }, [fromPush, screen, loadWatch]);

  const showC = useCallback(
    () =>
      api.today("pushed").then(
        (d) => setCRows(d.rows.filter((r) => r.grade === "C")),
        () => setCRows([]),
      ),
    [],
  );
  return { fromPush, screen, act, hiddenC, next, push, cRows, showC, positions, watch, loadWatch, error };
}

export function Today() {
  const d = useToday();
  const phone = useMedia(PHONE);
  const [sel, setSel] = useState<string | null>(null);
  const [tf, setTf] = useState<Timeframe>("1D");
  const [picked, setPicked] = useState<string[]>(DEFAULT_INDICATORS);
  const [flash, setFlash] = useState<string | null>(null);
  const [focusNote, setFocusNote] = useState(0);
  const noteRef = useRef<HTMLTextAreaElement>(null);

  const pinned = d.screen ? `From the screen: ${d.screen}` : "From the push";
  const sections = useMemo(() => {
    const out: { id: Kind; label: string; items: Item[] }[] = [];
    if (d.push.length) out.push({ id: "push", label: pinned, items: d.push.map((r) => rowItem("push", r)) });
    out.push({ id: "act", label: "To act on", items: (d.act ?? []).map((r) => rowItem("act", r)) });
    if (d.cRows) out.push({ id: "c", label: "C setups · no tested edge", items: d.cRows.map((r) => rowItem("c", r)) });
    out.push({
      id: "position",
      label: "Your positions",
      items: (d.positions?.cards ?? []).map((p) => ({ key: `position:${p.ticker}`, kind: "position", ticker: p.ticker, pos: p })),
    });
    out.push({ id: "watch", label: "Watching", items: d.watch.map((r) => rowItem("watch", r)) });
    return out;
  }, [d.push, d.act, d.cRows, d.positions, d.watch, pinned]);
  const items = useMemo(() => sections.flatMap((s) => s.items), [sections]);
  const actionable = sections.filter((s) => s.id === "push" || s.id === "act").flatMap((s) => s.items);
  const quiet = d.act !== null && actionable.length === 0;
  const current = items.find((i) => i.key === sel) ?? (sel === null && !quiet ? actionable[0] : undefined) ?? null;
  const index = current ? items.indexOf(current) : -1;
  const watchSet = useMemo(() => new Set(d.watch.map((r) => r.ticker)), [d.watch]);

  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 4000);
    return () => clearTimeout(t);
  }, [flash]);
  useEffect(() => {
    if (focusNote) noteRef.current?.focus();
  }, [focusNote]);

  const step = useCallback(
    (by: number) => {
      if (!items.length) return;
      const k = index < 0 ? (by > 0 ? 0 : items.length - 1) : (index + by + items.length) % items.length;
      setSel(items[k].key);
    },
    [items, index],
  );
  const toggleWatch = useCallback(
    (ticker: string) => {
      const on = watchSet.has(ticker);
      const call = on ? api.removeFromWatchlist(GREEN, [ticker]) : api.flag(ticker, GREEN);
      call.then(
        () => {
          setFlash(on ? `${ticker} is off your watchlist` : `${ticker} is on your watchlist`);
          d.loadWatch();
        },
        (e: Error) => setFlash(`Error: ${e.message}`),
      );
    },
    [watchSet, d],
  );

  // A layout effect: the listener is current as soon as a new queue is on screen
  useLayoutEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (document.querySelector(".palette-back")) return;
      const key = e.key.toLowerCase();
      if (e.key === "ArrowDown" || e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") step(-1);
      else if (key === "w" && current) toggleWatch(current.ticker);
      else if (key === "n" && current) setFocusNote((k) => k + 1);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, current, toggleWatch]);

  const nAct = (d.act ?? []).length;
  const title = titleLine(nAct, d.positions?.cards.length ?? 0, d.watch.length);
  const loading = d.act === null;

  const toast = flash && (
    <p className={`toast${flash.startsWith("Error") ? " error" : ""}`} role="status">
      {flash}
    </p>
  );

  if (phone) {
    return (
      <div className="today-phone">
        <div className="place-head">
          <h1>Today</h1>
          <span className="muted">{loading ? "Loading…" : title}</span>
        </div>
        {d.error && <p className="error">{d.error}</p>}
        {quiet && !current && <Quiet d={d} onPick={setSel} items={items} />}
        {current && (
          <PhoneCards
            items={items}
            current={current}
            onPick={setSel}
            watchSet={watchSet}
            onWatch={toggleWatch}
            onMessage={setFlash}
          />
        )}
        {toast}
      </div>
    );
  }

  return (
    <div>
      <div className="place-head">
        <h1>Today</h1>
        <span className="muted">{loading ? "Loading…" : title}</span>
      </div>
      {d.error && <p className="error">{d.error}</p>}
      <div className="today">
        <nav className="queue-col" aria-label="Queue">
          {sections.map((s) => (
            <div key={s.id}>
              <div className="section-label">
                <span>{s.label}</span>
                <span>{s.items.length || ""}</span>
              </div>
              {s.items.length === 0 ? (
                <p className="queue-note">{EMPTY[s.id]}</p>
              ) : (
                <ul className="queue">
                  {s.items.map((i) => (
                    <li key={i.key}>
                      <QueueRow item={i} active={current?.key === i.key} onPick={() => setSel(i.key)} />
                    </li>
                  ))}
                </ul>
              )}
              {s.id === "act" && d.hiddenC > 0 && !d.cRows && (
                <button className="link queue-note" onClick={d.showC}>
                  Show the {plural(d.hiddenC, "C setup")}
                </button>
              )}
            </div>
          ))}
          <p className="hotkeys">
            <kbd>↑</kbd> <kbd>↓</kbd> flip · <kbd>W</kbd> watch · <kbd>N</kbd> note
          </p>
        </nav>
        {!current ? (
          <div style={{ gridColumn: "2 / -1" }}>
            {loading ? <div className="quiet muted">Loading today's queue…</div> : <Quiet d={d} onPick={setSel} items={items} />}
          </div>
        ) : (
          <>
            <div className="center-col">
              <FocusChart
                ticker={current.ticker}
                levels={levelsOf(current)}
                anchor={(current.row?.avwap_anchor as string | null) ?? (current.row?.run_session as string | null) ?? null}
                tf={tf}
                onTf={setTf}
                picked={picked}
                onPicked={setPicked}
                price={priceOf(current)}
                change={changeOf(current)}
              />
              <FactStrip stats={statsOf(current)} />
            </div>
            <aside className="side-col" aria-label="Plan">
              <SidePanel item={current} />
              <WatchNote
                ticker={current.ticker}
                alertDefault={alertOf(current)}
                watching={watchSet.has(current.ticker)}
                onToggleWatch={() => toggleWatch(current.ticker)}
                noteRef={noteRef}
                onMessage={setFlash}
              />
            </aside>
          </>
        )}
      </div>
      {toast}
    </div>
  );
}

const EMPTY: Record<Kind, string> = {
  push: "",
  act: "No A+, A or B setups in the latest scans.",
  c: "No C setups.",
  position: "No open positions.",
  watch: "Star a stock to watch it here.",
};

function QueueRow({ item, active, onPick }: { item: Item; active: boolean; onPick: () => void }) {
  const chg = changeOf(item);
  const setup = item.row ? (item.kind === "watch" ? sectorOf(item.row) : item.row.scan_label) : item.pos!.setup;
  return (
    <button aria-current={active} className={active ? "active" : ""} onClick={onPick}>
      {item.kind === "watch" ? (
        <KindBadge kind="watch" />
      ) : item.kind === "position" ? (
        <KindBadge kind="position" />
      ) : (
        <GradeBadge grade={item.row!.grade} />
      )}
      <span className="tk">{item.ticker}</span>
      <span className="setup">{setup}</span>
      {typeof chg === "number" && (
        <span className={`chg num ${chg >= 0 ? "up" : "down"}`}>
          {chg >= 0 ? "+" : ""}
          {chg.toFixed(1)}%
        </span>
      )}
    </button>
  );
}

function sectorOf(row: BoardRow): string {
  return typeof row.industry === "string" ? row.industry : typeof row.sector === "string" ? row.sector : "";
}

function priceOf(i: Item): number | null {
  if (i.pos) return i.pos.price;
  return typeof i.row?.close === "number" ? (i.row.close as number) : null;
}

function changeOf(i: Item): number | null {
  if (i.pos) return i.pos.move_pct;
  return typeof i.row?.chg_pct === "number" ? i.row.chg_pct : null;
}

function levelsOf(i: Item): Record<string, number> {
  if (i.row) return i.row.levels ?? {};
  const out: Record<string, number> = {};
  if (i.pos?.entry) out.entry = i.pos.entry;
  if (i.pos?.stop) out.stop = i.pos.stop;
  return out;
}

function alertOf(i: Item): number {
  if (i.pos) return i.pos.stop ?? i.pos.entry;
  return typeof i.row?.alert_default === "number" ? (i.row.alert_default as number) : 0;
}

function statsOf(i: Item): Stat[] {
  if (i.row) return i.row.stats ?? [];
  const p = i.pos!;
  return [
    { label: "Shares", value: p.shares.toLocaleString("en-US") },
    { label: "Entry", value: p.entry.toFixed(2) },
    { label: "In since", value: p.entry_date },
    { label: "Stop", value: p.stop === null ? "no stop" : p.stop.toFixed(2) },
    { label: "To stop", value: p.to_stop_pct === null ? "–" : `${p.to_stop_pct.toFixed(1)}%` },
  ];
}

function SidePanel({ item }: { item: Item }) {
  if (item.pos) return <PositionPanel p={item.pos} />;
  const row = item.row!;
  if (item.kind === "watch") {
    return (
      <section className="card" aria-label={`${row.ticker} watch`}>
        <div className="plan head" style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <KindBadge kind="watch" />
          <b>{row.ticker}</b>
          <span className="muted">{sectorOf(row)}</span>
        </div>
        <p className="muted">On your watchlist. Not a scan hit today, so there is no plan or grade.</p>
        <a href={stockLink(row.ticker)}>Open the full chart</a>
      </section>
    );
  }
  if (!["A+", "A", "B", "C"].includes(row.grade)) {
    return (
      <section className="card" aria-label={`${row.ticker} screen`}>
        <b>{row.ticker}</b> <span className="muted">{row.run_label}</span>
        <p className="muted">A screen is a list to look at, not a tested setup: no grade, no buy.</p>
      </section>
    );
  }
  return (
    <>
      <PlanCard row={row} />
      <WhyCard row={row} />
    </>
  );
}

function PositionPanel({ p }: { p: PositionCard }) {
  return (
    <section className="card plan" aria-label={`${p.ticker} position`}>
      <div className="head">
        <KindBadge kind="position" />
        <span className="tk">{p.ticker}</span>
        <span className="muted">{p.setup}</span>
      </div>
      <div className="decision">
        {p.shares.toLocaleString("en-US")} shares since {p.entry_date}
      </div>
      <div className="decision-sub">
        {p.direction} at {p.entry.toFixed(2)}
      </div>
      <div className="quad">
        <div>
          <span>Price</span>
          <b className="num">{p.price === null ? "–" : p.price.toFixed(2)}</b>
        </div>
        <div>
          <span>Open R</span>
          <b className={`num ${p.open_r === null ? "" : p.open_r >= 0 ? "up" : "down"}`}>
            {p.open_r === null ? "–" : signed(p.open_r, 2, "R")}
          </b>
        </div>
        <div>
          <span>P&L</span>
          <b className={`num ${p.pnl === null ? "" : p.pnl >= 0 ? "up" : "down"}`}>{usd(p.pnl)}</b>
        </div>
        <div>
          <span>To stop</span>
          <b className="num">{p.to_stop_pct === null ? "no stop" : `${p.to_stop_pct.toFixed(1)}%`}</b>
        </div>
      </div>
      {p.facts.length > 0 && (
        <>
          <h3>What the plan says</h3>
          <ul>
            {p.facts.map((f) => (
              <li key={f} className={f.startsWith("⚠") ? "warn" : ""}>
                {stripIcons(f)}
              </li>
            ))}
          </ul>
        </>
      )}
      <a href={hrefFor("journal", "positions")}>All positions in the Journal</a>
    </section>
  );
}

function Quiet({
  d,
  onPick,
  items,
}: {
  d: ReturnType<typeof useToday>;
  onPick: (key: string) => void;
  items: Item[];
}) {
  const firstWatch = items.find((i) => i.kind === "watch");
  const firstC = items.find((i) => i.kind === "c");
  return (
    <section className="quiet" aria-label="Nothing to buy today">
      <div className="quiet-mark">
        <Icon name="moon" />
      </div>
      <h2>Nothing to buy today</h2>
      <p className="muted">No A+, A or B setups in the latest scans. Nothing to do is a fine day.</p>
      {d.next && (
        <p className="muted">
          Next scan: the {d.next.name}, {d.next.when}.
        </p>
      )}
      <div className="links">
        {d.hiddenC > 0 &&
          (firstC ? (
            <button onClick={() => onPick(firstC.key)}>Look at the C setups</button>
          ) : (
            <button onClick={d.showC}>See the {plural(d.hiddenC, "C setup")}</button>
          ))}
        {firstWatch ? (
          <button onClick={() => onPick(firstWatch.key)}>Your watchlist ({d.watch.length})</button>
        ) : (
          <a className="muted" href={hrefFor("stocks", "", { src: "lists" })}>
            Your watchlists
          </a>
        )}
        <a href={hrefFor("stocks", "", { src: "scans" })}>Every scan hit</a>
      </div>
    </section>
  );
}

// --- the phone: one card per stock, prev / next and dots

function PhoneCards({
  items,
  current,
  onPick,
  watchSet,
  onWatch,
  onMessage,
}: {
  items: Item[];
  current: Item;
  onPick: (key: string) => void;
  watchSet: Set<string>;
  onWatch: (t: string) => void;
  onMessage: (t: string) => void;
}) {
  const k = items.indexOf(current);
  const go = (by: number) => onPick(items[(k + by + items.length) % items.length].key);
  const touch = useRef<number | null>(null);
  return (
    <div
      onTouchStart={(e) => (touch.current = e.touches[0].clientX)}
      onTouchEnd={(e) => {
        if (touch.current === null) return;
        const dx = e.changedTouches[0].clientX - touch.current;
        touch.current = null;
        if (Math.abs(dx) > 60) go(dx < 0 ? 1 : -1);
      }}
    >
      <PhoneCard item={current} watching={watchSet.has(current.ticker)} onWatch={() => onWatch(current.ticker)} onMessage={onMessage} />
      <div className="flipper">
        <button className="icon-btn" aria-label="Previous stock" onClick={() => go(-1)} style={{ width: 44, height: 44 }}>
          <Icon name="left" />
        </button>
        <div className="dots" role="group" aria-label={`Stock ${k + 1} of ${items.length}`}>
          {items.map((i, n) => (
            <button key={i.key} aria-label={`${i.ticker}`} aria-current={n === k} onClick={() => onPick(i.key)} />
          ))}
        </div>
        <button className="icon-btn" aria-label="Next stock" onClick={() => go(1)} style={{ width: 44, height: 44 }}>
          <Icon name="right" />
        </button>
      </div>
    </div>
  );
}

function PhoneCard({
  item,
  watching,
  onWatch,
  onMessage,
}: {
  item: Item;
  watching: boolean;
  onWatch: () => void;
  onMessage: (t: string) => void;
}) {
  const row = item.row;
  const graded = row && ["A+", "A", "B", "C"].includes(row.grade) && item.kind !== "watch";
  const { view } = useTicket(graded ? row! : null, null, null);
  const [bars, setBars] = useState<{ t: string; c: Spark } | null>(null);
  useEffect(() => {
    let live = true;
    api.bars(item.ticker, "1D", []).then(
      (b) => live && setBars({ t: item.ticker, c: b.candles.slice(-60) }),
      () => live && setBars({ t: item.ticker, c: [] }),
    );
    return () => {
      live = false;
    };
  }, [item.ticker]);
  const price = priceOf(item);
  const chg = changeOf(item);
  const place = () =>
    api.placeTicket(row!, view?.kind ?? null, null).then(
      (r) => onMessage(r.message),
      (e: Error) => onMessage(`Error: ${e.message}`),
    );
  return (
    <article className="card phone-card" aria-label={`${item.ticker} card`}>
      <div className="head">
        {item.kind === "watch" || item.kind === "position" ? <KindBadge kind={item.kind} /> : <GradeBadge grade={row!.grade} large />}
        <span className="tk">{item.ticker}</span>
        <WatchButton watching={watching} onToggle={onWatch} compact />
        <div className="price">
          {price !== null && <div className="num">{price.toFixed(2)}</div>}
          {chg !== null && (
            <div className={`num ${chg >= 0 ? "up" : "down"}`}>
              {chg >= 0 ? "+" : ""}
              {chg.toFixed(1)}%
            </div>
          )}
        </div>
      </div>
      <div className="mini">
        {bars && bars.t === item.ticker ? (
          <MiniCandles candles={bars.c} levels={levelsOf(item)} height={140} label={item.ticker} />
        ) : (
          <div style={{ height: 140 }} />
        )}
      </div>
      {graded && (
        <>
          <div className="decision">{row!.decision?.text ?? (row!.grade === "C" ? "Not a buy by the study" : "Buy by the study's plan")}</div>
          <div className="decision-sub">{[row!.decision?.local, row!.decision?.day].filter(Boolean).join(" · ") || row!.scan_label}</div>
          <Numbers row={row!} view={view} three />
          <CopyOrder row={row!} view={view} big />
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="muted hint">{row!.scan_label}</span>
            <button className="link" onClick={place} disabled={!view?.ticket}>
              I placed it in Saxo
            </button>
          </div>
        </>
      )}
      {item.pos && (
        <div className="quad trio">
          <div>
            <span>Open R</span>
            <b className="num">{item.pos.open_r === null ? "–" : signed(item.pos.open_r, 2, "R")}</b>
          </div>
          <div>
            <span>Stop</span>
            <b className="num">{item.pos.stop === null ? "–" : item.pos.stop.toFixed(2)}</b>
          </div>
          <div>
            <span>Shares</span>
            <b className="num">{item.pos.shares.toLocaleString("en-US")}</b>
          </div>
        </div>
      )}
      {item.kind === "watch" && <FactStrip stats={statsOf(item)} />}
      <a href={stockLink(item.ticker)} className="hint">
        Full chart
      </a>
    </article>
  );
}

