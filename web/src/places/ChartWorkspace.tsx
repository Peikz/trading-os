// The Chart workspace (UX round 1, 18 Nov 2026), after TradingView and Finviz: one active stock
// (`#/chart?s=TICKER&list=ID`), the chart dominant, a list beside it to step through, and a
// bottom panel with the stock's plan, notes, position and journal. Up/Down (or J/K) move to the
// next stock on the list and the chart changes without a page load. On a phone the list is a
// bottom sheet and the header has the step arrows. Drawing (trend lines: draw, move, erase) is
// the existing DrawChart; the data is the existing chart API plus `/api/chart-lists`.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type ChartData, type ChartQuery, type TrendLine } from "../api";
import { DrawChart, type Point, type Tool } from "../components/DrawChart";
import { setActive, syncFromRoute, useActive } from "../shell/active";
import { CHART_SHOW, readPref, useArrowKeys, writePref } from "../shell/prefs";
import { nameOf, useNames } from "../shell/symbols";
import { ALL, chartListOf, useRunPick, useTodayRuns } from "../shell/todayRun";
import { PHONE, typing, useMedia } from "../ui/kit";
import { BottomPanel } from "./chart/BottomPanel";
import { type SortKey, sortRows, useChartList, useChartLists, useListView } from "./chart/lists";
import { PhoneHeader, SymbolBar, ToolRail, ToolsRow } from "./chart/SymbolBar";
import { ColumnsMenu, ListFilter, ListPicker, PhoneList, Sheet, WatchTable } from "./chart/WatchPanel";
import { GREEN } from "./today/WatchNote";

const FIRST_QUERY: ChartQuery = {
  period: "2y",
  timeframe: "Daily",
  span: "1Y",
  lines: ["MA10", "MA20", "MA50"],
  hits: true,
  fills: true,
  levels: true,
  anchors: [],
};

const CHART_SHOW_KEY = "chart-show";

function useWatching(symbol: string) {
  const [on, setOn] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const load = useCallback(
    () =>
      symbol
        ? api.watchlist(GREEN).then(
            (l) => setOn(l.rows.some((r) => String(r.ticker) === symbol)),
            () => setOn(false),
          )
        : Promise.resolve(),
    [symbol],
  );
  useEffect(() => {
    load();
  }, [load]);
  const toggle = () =>
    (on ? api.removeFromWatchlist(GREEN, [symbol]) : api.flag(symbol, GREEN)).then(
      () => {
        setMessage(on ? `${symbol} is off your watchlist` : `${symbol} is on your watchlist`);
        load();
      },
      (e: Error) => setMessage(`Error: ${e.message}`),
    );
  return { on, toggle, message };
}

export function ChartWorkspace({ params }: { params: URLSearchParams }) {
  const phone = useMedia(PHONE);
  const active = useActive();
  useEffect(() => syncFromRoute(params), [params]);

  // "Today's hits" follows the run picked on Today (All today, or one scan run)
  const [runPick, setRunPick] = useRunPick();
  useTodayRuns();
  const requested = active.list || "hits";
  const isToday = requested === "hits" || requested.startsWith("run:");
  const listId = isToday ? chartListOf(runPick) : requested;
  const urlList = isToday ? "hits" : listId; // the address keeps "hits"; the pick says which run
  const catalog = useChartLists();
  const { list, error: listError } = useChartList(listId);
  const { view, setSort, toggleColumn } = useListView(listId);
  const sort = view.sort;
  const [filter, setFilter] = useState("");
  useEffect(() => setFilter(""), [listId]);
  useNames();
  const sorted = useMemo(() => sortRows(list?.rows ?? [], sort), [list, sort]);
  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return sorted;
    return sorted.filter((r) => r.ticker.toLowerCase().includes(q) || r.setup.toLowerCase().includes(q) || nameOf(r.ticker).toLowerCase().includes(q));
  }, [sorted, filter]);
  const [arrowKeys] = useArrowKeys();
  const symbol = active.symbol;
  const at = rows.findIndex((r) => r.ticker === symbol);
  const row = at >= 0 ? rows[at] : undefined;

  // With no stock in the address, take the one you were on (Today's) or else the list's first
  const inAddress = params.has("s") || params.has("t");
  useEffect(() => {
    if (symbol && !inAddress) setActive(symbol);
    else if (!symbol && rows.length) setActive(rows[0].ticker, urlList);
  }, [symbol, inAddress, rows, urlList]);

  const step = useCallback(
    (by: 1 | -1) => {
      if (!rows.length) return;
      const next = at < 0 ? (by > 0 ? 0 : rows.length - 1) : at + by;
      if (next < 0 || next >= rows.length) return;
      setActive(rows[next].ticker, urlList);
    },
    [rows, at, urlList],
  );
  useEffect(() => {
    if (!arrowKeys) return;
    const onKey = (e: KeyboardEvent) => {
      if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "arrowdown" || k === "j") step(1);
      else if (k === "arrowup" || k === "k") step(-1);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, arrowKeys]);

  const pick = (t: string) => setActive(t, urlList);
  // A first click sorts best first (numbers high to low, words A to Z), a second flips, a third clears
  const onSort = (key: SortKey) =>
    setSort((s) => {
      const words = key === "ticker" || key === "setup" || key === "grade";
      if (!s || s.key !== key) return { key, down: !words };
      return s.down === !words ? { key, down: words } : null;
    });
  const listLabel = list?.label ?? catalog?.find((l) => l.id === listId)?.label ?? "List";
  const position = rows.length ? (at >= 0 ? `${listLabel} · ${at + 1} of ${rows.length}` : `${listLabel} · ${rows.length}`) : listLabel;
  const picker = (
    <ListPicker
      lists={catalog}
      value={listId}
      fallback={listLabel}
      onPick={(id) => {
        // Today's lists share the pick with the Today page
        if (id === "hits") setRunPick(ALL);
        else if (id.startsWith("run:")) setRunPick(id.slice(4));
        setActive(symbol, id === "hits" || id.startsWith("run:") ? "hits" : id);
      }}
    />
  );

  // The chart
  const [q, setQ] = useState<ChartQuery>(() => ({ ...FIRST_QUERY, ...readPref(CHART_SHOW_KEY, CHART_SHOW) }));
  useEffect(() => writePref(CHART_SHOW_KEY, { hits: q.hits, fills: q.fills, levels: q.levels }), [q.hits, q.fills, q.levels]);
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("none");
  const [flash, setFlash] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [sideOpen, setSideOpen] = useState(true);
  const [bottomOpen, setBottomOpen] = useState(true);
  const watching = useWatching(symbol);

  useEffect(() => {
    if (!symbol) return setData(null);
    let live = true;
    setError(null);
    const timer = setTimeout(() => {
      api.chart(symbol, q).then(
        (d) => live && setData(d),
        (e: Error) => live && setError(e.message),
      );
    }, 120);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [symbol, q, version]);
  useEffect(() => {
    if (!flash) return;
    const gone = setTimeout(() => setFlash(null), 6000);
    return () => clearTimeout(gone);
  }, [flash]);
  useEffect(() => {
    if (watching.message) setFlash(watching.message);
  }, [watching.message]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const fail = (e: Error) => setFlash(`Error: ${e.message}`);
  const fresh = data !== null && data.ticker === symbol;
  const daily = q.timeframe === "Daily";
  const draw = (a: Point, b: Point, extend: boolean) =>
    api.addLine(symbol, { x0: a.time, y0: a.price, x1: b.time, y1: b.price, extend }).then(() => {
      setFlash("Line saved.");
      reload();
    }, fail);
  const move = (l: TrendLine, a: Point, b: Point) =>
    api.moveLine(symbol, l.id, { x0: a.time, y0: a.price, x1: b.time, y1: b.price, extend: l.extend }).then(() => {
      setFlash("Line moved.");
      reload();
    }, fail);
  const erase = (l: TrendLine) =>
    api.removeMark(symbol, l.id).then(() => {
      setFlash("Line deleted.");
      reload();
    }, fail);

  const bar = {
    symbol,
    row,
    data,
    q,
    setQ,
    position,
    canPrev: rows.length > 0 && at !== 0,
    canNext: rows.length > 0 && at < rows.length - 1,
    onStep: step,
    watching: watching.on,
    onWatch: watching.toggle,
    sideOpen,
    onSide: () => setSideOpen((o) => !o),
  };
  const toolsOn = daily && fresh;

  const chart = (
    <div className={`ws-chart${fresh ? "" : " stale"}`}>
      {error && <p className="error ws-note">{error}</p>}
      {listError && <p className="error ws-note">{listError}</p>}
      {!symbol && !error && <p className="muted ws-empty">Pick a stock from the list, or press / to search.</p>}
      {data && data.candles.length > 0 && (
        <DrawChart data={data} height="fill" markerText={false} tool={toolsOn ? tool : "none"} onDraw={draw} onMove={move} onErase={erase} />
      )}
      {data && fresh && data.candles.length === 0 && <p className="muted ws-empty">No daily bars for {symbol} in the data repo yet.</p>}
      {flash && (
        <p className="flash" role="status">
          {flash}
        </p>
      )}
    </div>
  );
  const bottom = (
    <BottomPanel
      symbol={symbol}
      data={data}
      row={row}
      open={bottomOpen}
      onToggle={() => setBottomOpen((o) => !o)}
      onMessage={setFlash}
      onSaved={reload}
    />
  );

  if (phone) {
    return (
      <div className="ws phone">
        <h1 className="sr-only">Chart</h1>
        <PhoneHeader {...bar} />
        {chart}
        <ToolsRow q={q} setQ={setQ} data={data} tool={tool} onTool={setTool} enabled={toolsOn} />
        {bottom}
        <Sheet title={position}>
          <div className="sheet-picker">
            {picker}
            <ListFilter value={filter} onChange={setFilter} />
          </div>
          <PhoneList rows={rows} symbol={symbol} onPick={pick} filtered={filter.trim() !== ""} />
        </Sheet>
      </div>
    );
  }
  return (
    <div className="ws">
      <h1 className="sr-only">Chart</h1>
      <SymbolBar {...bar} />
      <div className={`ws-main${sideOpen ? "" : " no-side"}`}>
        <ToolRail tool={tool} onTool={setTool} enabled={toolsOn} />
        {chart}
        {sideOpen && (
          <aside className="ws-side" aria-label="List panel">
            <div className="ws-side-head">
              <div className="side-pick">
                {picker}
                <ColumnsMenu hidden={view.hidden} onToggle={toggleColumn} />
              </div>
              <ListFilter value={filter} onChange={setFilter} />
            </div>
            <WatchTable
              rows={rows}
              symbol={symbol}
              onPick={pick}
              sort={sort}
              onSort={onSort}
              label={listLabel}
              hidden={view.hidden}
              filtered={filter.trim() !== ""}
            />
          </aside>
        )}
      </div>
      {bottom}
    </div>
  );
}
