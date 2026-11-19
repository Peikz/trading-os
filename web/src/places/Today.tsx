// Today: "What do I do today?" (design review 4 Nov 2026). Left, the queue in three parts: TO ACT
// ON (A+ / A / B), YOUR POSITIONS and WATCHING (Flag green). Centre, the chart and a quiet strip
// of key facts. Right, the plan card that leads with the decision, why the grade, then Watch and
// a note. Arrow keys flip the queue, F watches, N writes a note, T opens the Saxo values and W steps
// the bars. A quiet day (no A+ / A / B) shows a calm "Nothing to buy today" with the way on: the C
// setups, your watchlist and the next scan. A push link (`?t=A,B`) or a screen's flip link
// (`#/today?screen=Name&t=A,B`) puts those stocks first.
//
// The calm layout (19 Nov 2026, owner-approved mockup): Focus is a market line, a compact "To act
// on" list, ONE big card for the selected stock and, right, positions, alerts and the day's note.
// Why, key facts, the Saxo order, the note and the price alert sit behind "Why and facts".
//
// Round 4 (19 Nov 2026), the last of Streamlit's board: the view (Focus, Grid of four charts, List
// of cards), "Show" (today's list, the pushed scans with the C setups, every hit, or one of your
// watchlists), a run picker that reaches earlier days, "All scans" (every pushed scan's table)
// and, on a phone, one card per stock with the order's edit, copy, why, note, alert and bars.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type BoardRow, DEFAULT_INDICATORS, type NextScan, type Positions, type Timeframe } from "../api";
import { DailyNote } from "../components/DailyNote";
import { hrefFor } from "../routes";
import { setActive } from "../shell/active";
import { useArrowKeys, usePref } from "../shell/prefs";
import { useEarlierRuns, useRunPick, useTodayRuns } from "../shell/todayRun";
import { RunPicker } from "../ui/RunPicker";
import { Icon } from "../ui/Icon";
import { PHONE, typing, useMedia } from "../ui/kit";
import { AllScans } from "./today/AllScans";
import { ActRow, AlertsLine, Chips, GroupLine, MarketLine, PositionsList, StockCard } from "./today/Calm";
import { ShowMenu, ViewToggle } from "./today/Controls";
import { TIMEFRAMES } from "./today/FocusChart";
import {
  type Item,
  type Kind,
  plural,
  pushTickers,
  rowItem,
  screenName,
  SCOPE_ALL,
  SCOPE_LIST,
  SCOPE_PUSHED,
  SCOPE_TODAY,
  scopeLabel,
  titleLine,
  todayQuery,
  type View,
} from "./today/model";
import { VALUES_EVENT } from "./today/PlanCard";
import { GridView, GRID, ListView } from "./today/Views";
import { GREEN } from "./today/WatchNote";

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
  const [more, setMore] = useState<"watch" | "c" | null>(null);
  const touch = useRef<number | null>(null);

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

  // The C setups (opened by "C setups", or by the quiet day's link) and the watched stocks sit
  // under the list; a stock stepped to with the keys opens its group
  useEffect(() => {
    if (d.cRows) setMore("c");
  }, [d.cRows]);
  useEffect(() => {
    if (currentKind === "c" || currentKind === "watch") setMore(currentKind);
  }, [currentKind]);
  const openMore = (m: "watch" | "c" | null) => {
    if (m === "c" && !d.cRows) d.showC();
    setMore(m);
  };
  const listSections = todays ? sections.filter((s) => s.id === "push" || s.id === "act") : sections;
  const extra = todays && more ? (sections.find((s) => s.id === more)?.items ?? []) : [];
  const stepItems = [...listSections.flatMap((s) => s.items), ...extra];
  const cCount = d.cRows ? d.cRows.length : d.hiddenC;

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
        setMore(null);
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
  const card = current && (
    <StockCard
      item={current}
      phone={phone}
      tf={tf}
      onTf={setTf}
      picked={picked}
      onPicked={setPicked}
      watching={watchSet.has(current.ticker)}
      onWatch={() => toggleWatch(current.ticker)}
      onMessage={setFlash}
      noteRef={noteRef}
      noteSignal={focusNote}
    />
  );
  const positions = <PositionsList cards={d.positions?.cards ?? []} current={current?.key ?? null} onPick={setSel} />;

  if (phone) {
    const k = current ? stepItems.indexOf(current) : -1;
    const go = (by: number) => {
      if (stepItems.length) setSel(stepItems[(Math.max(k, 0) + by + stepItems.length) % stepItems.length].key);
    };
    return (
      <div className="today-phone calm-phone">
        {head}
        {d.error && <p className="error">{d.error}</p>}
        <MarketLine next={d.next} />
        {picker}
        {stepItems.length > 0 && <Chips items={stepItems} current={current?.key ?? null} onPick={setSel} />}
        {todays && <GroupLine watch={d.watch.length} c={cCount} more={more} onMore={openMore} />}
        {quiet && !current && <Quiet d={d} onPick={setSel} items={items} />}
        {card && (
          <div
            onTouchStart={(e) => (touch.current = e.touches[0].clientX)}
            onTouchEnd={(e) => {
              if (touch.current === null) return;
              const dx = e.changedTouches[0].clientX - touch.current;
              touch.current = null;
              if (Math.abs(dx) > 60) go(dx < 0 ? 1 : -1);
            }}
          >
            {card}
          </div>
        )}
        {positions}
        <DailyNote />
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

  const rows = (list: Item[]) => (
    <ul className="queue">
      {list.map((i) => (
        <li key={i.key}>
          <ActRow item={i} active={current?.key === i.key} onPick={() => setSel(i.key)} slotNames={slotNames} />
        </li>
      ))}
    </ul>
  );
  const group = (label: string, list: Item[]) => (
    <div>
      <div className="section-label">
        <span>{label}</span>
        <span>{list.length || ""}</span>
      </div>
      {rows(list)}
    </div>
  );
  return (
    <div className="calm">
      {head}
      {d.error && <p className="error">{d.error}</p>}
      {picker}
      <MarketLine next={d.next} />
      <div className="calm-grid">
        <nav className="queue-col calm-left" aria-label="Queue">
          {listSections.map((s) => (
            <div key={s.id}>
              <div className="section-label">
                <span>{s.label}</span>
                <span>{s.items.length ? (s.id === "act" && todays ? `${s.items.length} today` : s.items.length) : ""}</span>
              </div>
              {s.items.length === 0 ? <p className="queue-note">{s.empty ?? EMPTY[s.id]}</p> : rows(s.items)}
            </div>
          ))}
          {todays && (
            <>
              <GroupLine watch={d.watch.length} c={cCount} more={more} onMore={openMore} />
              {more === "c" && d.cRows && group("C setups · no tested edge", extra)}
              {more === "watch" && group("Watching", extra)}
            </>
          )}
          <p className="hotkeys">
            <kbd>↑</kbd> <kbd>↓</kbd> flip · <kbd>F</kbd> watch · <kbd>N</kbd> note · <kbd>T</kbd> Saxo values · <kbd>W</kbd> bars
          </p>
        </nav>
        <div className="calm-main">
          {!current ? (
            loading ? (
              <div className="quiet muted">Loading today&apos;s queue…</div>
            ) : (
              <Quiet d={d} onPick={setSel} items={items} />
            )
          ) : (
            card
          )}
        </div>
        <aside className="calm-right" aria-label="Positions and alerts">
          {positions}
          <AlertsLine />
          <DailyNote />
        </aside>
      </div>
      {allScans}
      {toast}
    </div>
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

