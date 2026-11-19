// Today: "What do I do today?" (design review 4 Nov 2026). Left, the queue in three parts: TO ACT
// ON (A+ / A / B), YOUR POSITIONS and WATCHING (Flag green). Centre, the chart and a quiet strip
// of key facts. Right, the plan card that leads with the decision, why the grade, then Watch and
// a note. Arrow keys flip the queue, F watches, N writes a note, T opens the Saxo values and W steps
// the bars. A quiet day (no A+ / A / B) shows a calm "Nothing to buy today" with the way on: the C
// setups, your watchlist and the next scan. A push link (`?t=A,B`) or a screen's flip link
// (`#/today?screen=Name&t=A,B`) puts those stocks first.
//
// Round 4 (19 Nov 2026), the last of Streamlit's board: the view (Focus, Grid of four charts, List
// of cards), "Show" (today's list, the pushed scans with the C setups, every hit, or one of your
// watchlists), a run picker that reaches earlier days, "All scans" (every pushed scan's table)
// and, on a phone, one card per stock with the order's edit, copy, why, note, alert and bars.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type BoardRow, DEFAULT_INDICATORS, type NextScan, type Positions, type Timeframe } from "../api";
import { FactStrip, GradeBadge, KindBadge } from "../components/Card";
import { DailyNote } from "../components/DailyNote";
import { signed } from "../format";
import { hrefFor, stockLink } from "../routes";
import { setActive } from "../shell/active";
import { useArrowKeys, usePref } from "../shell/prefs";
import { useEarlierRuns, useRunPick, useTodayRuns } from "../shell/todayRun";
import { RunPicker } from "../ui/RunPicker";
import { Icon } from "../ui/Icon";
import { PHONE, typing, useMedia } from "../ui/kit";
import { AllScans } from "./today/AllScans";
import { ShowMenu, ViewToggle } from "./today/Controls";
import { FocusChart, TIMEFRAMES } from "./today/FocusChart";
import {
  alertOf,
  anchorOf,
  changeOf,
  type Item,
  type Kind,
  levelsOf,
  plural,
  priceOf,
  pushTickers,
  rowItem,
  screenName,
  SCOPE_ALL,
  SCOPE_LIST,
  SCOPE_PUSHED,
  SCOPE_TODAY,
  scopeLabel,
  sectorOf,
  statsOf,
  titleLine,
  todayQuery,
  type View,
} from "./today/model";
import { SidePanel } from "./today/Panels";
import { CopyOrder, EditOrder, Numbers, OrderLine, PlaceOrder, usePlan, VALUES_EVENT, WhyCard } from "./today/PlanCard";
import { GridView, GRID, ListView } from "./today/Views";
import { GREEN, WatchButton, WatchNote } from "./today/WatchNote";

export { pushTickers, screenName, titleLine };

/** The query of the address, kept current: a flip link from the Screener changes only the hash. */
function useTodayQuery(): string {
  const [q, setQ] = useState(() => todayQuery(window.location));
  useEffect(() => {
    const on = () => setQ(todayQuery(window.location));
    window.addEventListener("hashchange", on);
    window.addEventListener("popstate", on);
    return () => {
      window.removeEventListener("hashchange", on);
      window.removeEventListener("popstate", on);
    };
  }, []);
  return q;
}

function useToday(run: string, scope: string) {
  const query = useTodayQuery();
  const fromPush = useMemo(() => pushTickers(query), [query]);
  const screen = useMemo(() => screenName(query), [query]);
  const [act, setAct] = useState<BoardRow[] | null>(null);
  const [hiddenC, setHiddenC] = useState(0);
  const [next, setNext] = useState<NextScan | null>(null);
  const [push, setPush] = useState<BoardRow[]>([]);
  const [cRows, setCRows] = useState<BoardRow[] | null>(null);
  const [positions, setPositions] = useState<Positions | null>(null);
  const [watch, setWatch] = useState<BoardRow[]>([]);
  const [lists, setLists] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadWatch = useCallback(
    () => api.today("watchlists", [], null, GREEN).then((d) => setWatch(d.rows), () => setWatch([])),
    [],
  );
  // The list shown: today's graded queue (of the run picked at the top), or what "Show" picked
  useEffect(() => {
    let live = true;
    setCRows(null);
    const list = scope.startsWith(SCOPE_LIST) ? scope.slice(SCOPE_LIST.length) : null;
    const call =
      scope === SCOPE_PUSHED
        ? api.today("pushed", [], null, null, run)
        : scope === SCOPE_ALL
          ? api.today("all", [], null, null, run)
          : list !== null
            ? api.today("watchlists", [], null, list)
            : api.today("graded", [], null, null, run);
    call.then(
      (d) => {
        if (!live) return;
        setAct(d.rows);
        setHiddenC(d.hidden_c);
        setNext(d.next_scan ?? null);
        setError(null);
      },
      (e: Error) => {
        if (!live) return;
        setAct([]);
        setError(e.message);
      },
    );
    return () => {
      live = false;
    };
  }, [run, scope]);
  useEffect(() => {
    if (fromPush.length) api.today("all", fromPush, screen).then((d) => setPush(d.rows), () => setPush([]));
    else setPush([]);
  }, [fromPush, screen]);
  useEffect(() => {
    api.positions().then(setPositions, () => setPositions(null));
    api.watchlists().then((w) => setLists(w.lists), () => setLists([]));
    loadWatch();
  }, [loadWatch]);

  const showC = useCallback(
    () =>
      api.today("pushed", [], null, null, run).then(
        (d) => setCRows(d.rows.filter((r) => r.grade === "C")),
        () => setCRows([]),
      ),
    [run],
  );
  return { fromPush, screen, act, hiddenC, next, push, cRows, showC, positions, watch, lists, loadWatch, error };
}

const EMPTY: Record<Kind, string> = {
  push: "",
  act: "No A+, A or B setups in the latest scans.",
  c: "No C setups.",
  position: "No open positions.",
  watch: "Star a stock to watch it here.",
};

export function Today() {
  const [run, setRun] = useRunPick();
  const runs = useTodayRuns();
  const earlier = useEarlierRuns(runs);
  const [view, setView] = usePref<View>("today-view", "Focus");
  const [scope, setScope] = usePref<string>("today-scope", SCOPE_TODAY);
  const d = useToday(run, scope);
  const [arrowKeys] = useArrowKeys();
  const phone = useMedia(PHONE);
  const [sel, setSel] = useState<string | null>(null);
  const [gridAt, setGridAt] = useState(0);
  const slotNames = useMemo(() => Object.fromEntries((runs?.runs ?? []).map((r) => [r.slot, r.name])), [runs]);
  // A list that is gone (deleted since) falls back to today's
  useEffect(() => {
    if (scope.startsWith(SCOPE_LIST) && d.lists.length && !d.lists.includes(scope.slice(SCOPE_LIST.length))) setScope(SCOPE_TODAY);
  }, [scope, d.lists, setScope]);
  const todays = scope === SCOPE_TODAY;
  const isList = scope.startsWith(SCOPE_LIST);
  const picker = !isList && (
    <RunPicker
      runs={runs}
      value={run}
      earlier={earlier}
      onPick={(id) => {
        setRun(id);
        setSel(null);
        setGridAt(0);
      }}
    />
  );
  const [tf, setTf] = useState<Timeframe>("1D");
  const [picked, setPicked] = useState<string[]>(DEFAULT_INDICATORS);
  const [flash, setFlash] = useState<string | null>(null);
  const [focusNote, setFocusNote] = useState(0);
  const noteRef = useRef<HTMLTextAreaElement>(null);

  const pinned = d.screen ? `From the screen: ${d.screen}` : "From the push";
  const sections = useMemo(() => {
    const out: { id: Kind; label: string; items: Item[]; empty?: string }[] = [];
    if (d.push.length) out.push({ id: "push", label: pinned, items: d.push.map((r) => rowItem("push", r)) });
    if (todays) {
      out.push({ id: "act", label: "To act on", items: (d.act ?? []).map((r) => rowItem("act", r)) });
      if (d.cRows) out.push({ id: "c", label: "C setups · no tested edge", items: d.cRows.map((r) => rowItem("c", r)) });
      out.push({
        id: "position",
        label: "Your positions",
        items: (d.positions?.cards ?? []).map((p) => ({ key: `position:${p.ticker}`, kind: "position", ticker: p.ticker, pos: p })),
      });
      out.push({ id: "watch", label: "Watching", items: d.watch.map((r) => rowItem("watch", r)) });
    } else {
      out.push({
        id: "act",
        label: scopeLabel(scope),
        items: (d.act ?? []).map((r) => rowItem(isList ? "watch" : "act", r)),
        empty: isList ? "This watchlist is empty: star a stock, or add to it on the Watchlists page." : "No signals in the latest runs.",
      });
    }
    return out;
  }, [d.push, d.act, d.cRows, d.positions, d.watch, pinned, todays, scope, isList]);
  const items = useMemo(() => sections.flatMap((s) => s.items), [sections]);
  const actionable = sections.filter((s) => s.id === "push" || s.id === "act").flatMap((s) => s.items);
  const quiet = todays && d.act !== null && actionable.length === 0;
  const gridCurrent = view === "Grid" ? items[Math.min(gridAt, Math.max(0, items.length - 1))] : undefined;
  const current = items.find((i) => i.key === sel) ?? gridCurrent ?? (sel === null && !quiet ? actionable[0] : undefined) ?? null;
  const index = current ? items.indexOf(current) : -1;
  const watchSet = useMemo(() => new Set(d.watch.map((r) => r.ticker)), [d.watch]);

  // The stock on screen is the active one: the Chart opens on it
  const currentTicker = current?.ticker;
  const currentKind = current?.kind;
  useEffect(() => {
    // A scan hit brings today's list with it, so the Chart steps through the same stocks
    const today = currentKind === "act" || currentKind === "push" || currentKind === "c";
    if (currentTicker) setActive(currentTicker, today ? "hits" : undefined);
  }, [currentTicker, currentKind]);
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
  const stepGrid = useCallback(
    (by: number) => {
      if (!items.length) return;
      const pages = Math.ceil(items.length / GRID);
      const page = Math.floor(gridAt / GRID);
      setGridAt((((page + by + pages) % pages) * GRID));
      setSel(null);
    },
    [items, gridAt],
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
      const next = e.key === "ArrowDown" || e.key === "ArrowRight";
      const prev = e.key === "ArrowUp" || e.key === "ArrowLeft";
      if (arrowKeys && (next || prev)) (view === "Grid" ? stepGrid : step)(next ? 1 : -1);
      else if (key === "f" && current) toggleWatch(current.ticker);
      else if (key === "w") setTf((t) => TIMEFRAMES[(TIMEFRAMES.indexOf(t) + 1) % TIMEFRAMES.length]);
      else if (key === "t" && current) window.dispatchEvent(new Event(VALUES_EVENT));
      else if (key === "n" && current) setFocusNote((k) => k + 1);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, stepGrid, current, toggleWatch, arrowKeys, view]);

  const nAct = (d.act ?? []).length;
  const title = todays
    ? titleLine(nAct, d.positions?.cards.length ?? 0, d.watch.length)
    : `${plural(nAct, "stock")} · ${scopeLabel(scope)}`;
  const loading = d.act === null;

  const toast = flash && (
    <p className={`toast${flash.startsWith("Error") ? " error" : ""}`} role="status">
      {flash}
    </p>
  );
  const showMenu = (
    <ShowMenu
      value={scope}
      lists={d.lists}
      onPick={(s) => {
        setScope(s);
        setSel(null);
        setGridAt(0);
      }}
    />
  );
  const head = (
    <div className="place-head">
      <h1>Today</h1>
      <span className="muted">{loading ? "Loading…" : title}</span>
      <span className="grow" />
      {!phone && <ViewToggle value={view} onPick={setView} />}
      {showMenu}
    </div>
  );
  const allScans = <AllScans runs={runs} earlier={earlier} picked={run} />;

  if (phone) {
    return (
      <div className="today-phone">
        {head}
        {d.error && <p className="error">{d.error}</p>}
        <DailyNote />
        {picker}
        {quiet && !current && <Quiet d={d} onPick={setSel} items={items} />}
        {current && (
          <PhoneCards
            items={items}
            current={current}
            onPick={setSel}
            watchSet={watchSet}
            onWatch={toggleWatch}
            onMessage={setFlash}
            tf={tf}
            onTf={setTf}
            picked={picked}
            onPicked={setPicked}
          />
        )}
        {allScans}
        {toast}
      </div>
    );
  }

  if (view !== "Focus") {
    return (
      <div>
        {head}
        {d.error && <p className="error">{d.error}</p>}
        <DailyNote />
        {picker}
        {loading ? (
          <div className="quiet muted">Loading today&apos;s list…</div>
        ) : view === "Grid" ? (
          <GridView
            items={items}
            at={gridAt}
            onAt={(i) => {
              setGridAt(i);
              setSel(null);
            }}
            current={current?.key ?? null}
            onSelect={setSel}
            tf={tf}
            onTf={setTf}
            picked={picked}
            onPicked={setPicked}
          />
        ) : (
          <ListView items={items} slotNames={slotNames} />
        )}
        {allScans}
        {toast}
      </div>
    );
  }

  return (
    <div>
      {head}
      {d.error && <p className="error">{d.error}</p>}
      <DailyNote />
      <div className="today">
        <nav className="queue-col" aria-label="Queue">
          {sections.map((s) => (
            <div key={s.id}>
              <div className="section-label">
                <span>{s.label}</span>
                <span>{s.items.length || ""}</span>
              </div>
              {s.id === "act" && picker}
              {s.items.length === 0 ? (
                <p className="queue-note">{s.empty ?? EMPTY[s.id]}</p>
              ) : (
                <ul className="queue">
                  {s.items.map((i) => (
                    <li key={i.key}>
                      <QueueRow item={i} active={current?.key === i.key} onPick={() => setSel(i.key)} slotNames={slotNames} />
                    </li>
                  ))}
                </ul>
              )}
              {s.id === "act" && todays && d.hiddenC > 0 && !d.cRows && (
                <button className="link queue-note" onClick={d.showC}>
                  Show the {plural(d.hiddenC, "C setup")}
                </button>
              )}
            </div>
          ))}
          <p className="hotkeys">
            <kbd>↑</kbd> <kbd>↓</kbd> flip · <kbd>F</kbd> watch · <kbd>N</kbd> note · <kbd>T</kbd> Saxo values · <kbd>W</kbd> bars
          </p>
        </nav>
        {!current ? (
          <div style={{ gridColumn: "2 / -1" }}>
            {loading ? <div className="quiet muted">Loading today&apos;s queue…</div> : <Quiet d={d} onPick={setSel} items={items} />}
          </div>
        ) : (
          <>
            <div className="center-col">
              <FocusChart
                ticker={current.ticker}
                levels={levelsOf(current)}
                anchor={anchorOf(current)}
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
      {allScans}
      {toast}
    </div>
  );
}

function QueueRow({
  item,
  active,
  onPick,
  slotNames,
}: {
  item: Item;
  active: boolean;
  onPick: () => void;
  slotNames: Record<string, string>;
}) {
  const chg = changeOf(item);
  const many = Object.keys(slotNames).length > 1;
  const from = (item.row?.runs ?? []).map((s) => slotNames[s] ?? s).join(" · ");
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
      <span className="setup">
        {setup}
        {from && many && <small className="from-runs">{from}</small>}
      </span>
      {typeof chg === "number" && (
        <span className={`chg num ${chg >= 0 ? "up" : "down"}`}>
          {chg >= 0 ? "+" : ""}
          {chg.toFixed(1)}%
        </span>
      )}
    </button>
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
          <a className="muted" href={hrefFor("watchlists")}>
            Your watchlists
          </a>
        )}
        <a href={hrefFor("screener", "hits")}>Every scan hit</a>
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
  tf,
  onTf,
  picked,
  onPicked,
}: {
  items: Item[];
  current: Item;
  onPick: (key: string) => void;
  watchSet: Set<string>;
  onWatch: (t: string) => void;
  onMessage: (t: string) => void;
  tf: Timeframe;
  onTf: (t: Timeframe) => void;
  picked: string[];
  onPicked: (p: string[]) => void;
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
      <PhoneCard
        item={current}
        watching={watchSet.has(current.ticker)}
        onWatch={() => onWatch(current.ticker)}
        onMessage={onMessage}
        tf={tf}
        onTf={onTf}
        picked={picked}
        onPicked={onPicked}
      />
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

/** The phone card's order: the plan's numbers, one big copy button, the order on a line with
 * "Edit order" (type, own price, the shares follow, each value to copy) and "I placed it in Saxo". */
function PhoneOrder({ row }: { row: BoardRow }) {
  const plan = usePlan(row);
  return (
    <>
      <Numbers row={row} view={plan.view} three />
      <CopyOrder row={row} view={plan.view} big />
      <OrderLine plan={plan} />
      <EditOrder plan={plan} />
      <PlaceOrder plan={plan} />
    </>
  );
}

function PhoneCard({
  item,
  watching,
  onWatch,
  onMessage,
  tf,
  onTf,
  picked,
  onPicked,
}: {
  item: Item;
  watching: boolean;
  onWatch: () => void;
  onMessage: (t: string) => void;
  tf: Timeframe;
  onTf: (t: Timeframe) => void;
  picked: string[];
  onPicked: (p: string[]) => void;
}) {
  const row = item.row;
  const graded = row && ["A+++", "A++", "A+", "A", "B", "C"].includes(row.grade) && item.kind !== "watch";
  const price = priceOf(item);
  const chg = changeOf(item);
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
        <FocusChart
          ticker={item.ticker}
          levels={levelsOf(item)}
          anchor={anchorOf(item)}
          tf={tf}
          onTf={onTf}
          picked={picked}
          onPicked={onPicked}
          height={200}
          head={false}
        />
      </div>
      {graded && (
        <>
          <div className="decision">{row!.decision?.text ?? (row!.grade === "C" ? "Not a buy by the study" : "Buy by the study's plan")}</div>
          <div className="decision-sub">{[row!.decision?.local, row!.decision?.day].filter(Boolean).join(" · ") || row!.scan_label}</div>
          <PhoneOrder row={row!} />
          <details className="phone-more">
            <summary>Why {row!.grade}</summary>
            <WhyCard row={row!} />
          </details>
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
      <details className="phone-more">
        <summary>Note and price alert</summary>
        <WatchNote
          ticker={item.ticker}
          alertDefault={alertOf(item)}
          watching={watching}
          onToggleWatch={onWatch}
          onMessage={onMessage}
        />
      </details>
      <a href={stockLink(item.ticker)} className="hint">
        Full chart
      </a>
    </article>
  );
}

