// The Chart's lists: the picker's catalog, one list's rows (sortable), and the 20-day sparklines
// (one `/api/sparks` call per 60 stocks, kept for the visit so a list you come back to is
// drawn at once).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ChartList, type ChartListInfo, type ChartListRow } from "../../api";
import { readLastScreen, readPref, writePref } from "../../shell/prefs";

export function useChartLists(): ChartListInfo[] | null {
  const [lists, setLists] = useState<ChartListInfo[] | null>(null);
  useEffect(() => {
    const load = () =>
      api.chartLists().then(
        (r) => setLists(withScreen(r.lists)),
        () => setLists(withScreen([])),
      );
    load();
    window.addEventListener("trading-os:refresh", load);
    return () => window.removeEventListener("trading-os:refresh", load);
  }, []);
  return lists;
}

/** "Last screener result": the stocks of the Screener's last result (opened from All stocks or a
 * saved screen), as the Streamlit Chart lists them. Listed only once a screen has been opened. */
function withScreen(lists: ChartListInfo[]): ChartListInfo[] {
  const last = readLastScreen();
  if (!last.length) return lists;
  return [...lists, { id: "screen", label: "Last screener result", group: "Screener", count: last.length }];
}

export function useChartList(id: string): { list: ChartList | null; error: string | null } {
  const [state, setState] = useState<{ id: string; list: ChartList | null; error: string | null }>({
    id: "",
    list: null,
    error: null,
  });
  useEffect(() => {
    let live = true;
    const load = () =>
      api.chartList(id, id === "screen" ? readLastScreen() : undefined).then(
        (list) => live && setState({ id, list, error: null }),
        (e: Error) => live && setState({ id, list: null, error: e.message }),
      );
    load();
    window.addEventListener("trading-os:refresh", load);
    return () => {
      live = false;
      window.removeEventListener("trading-os:refresh", load);
    };
  }, [id]);
  return state.id === id ? { list: state.list, error: state.error } : { list: null, error: null };
}

export type SortKey = "ticker" | "grade" | "last" | "chg_pct" | "rvol" | "setup";
export interface Sort {
  key: SortKey;
  down: boolean;
}

const GRADE_RANK: Record<string, number> = { "A+++": 0, "A++": 1, "A+": 2, A: 3, B: 4, C: 5, "": 9 };

/** The rows in the order shown; no sort keeps the list's own (best grade first). Blanks last. */
export function sortRows(rows: ChartListRow[], sort: Sort | null): ChartListRow[] {
  if (!sort) return rows;
  const { key, down } = sort;
  const value = (r: ChartListRow): number | string | null => {
    if (key === "grade") return GRADE_RANK[r.grade] ?? 8;
    if (key === "ticker" || key === "setup") return r[key] || null;
    return r[key];
  };
  return [...rows].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    if (x === null && y === null) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    const c = typeof x === "string" ? x.localeCompare(String(y)) : (x as number) - (y as number);
    return down ? -c : c;
  });
}

const sparkCache = new Map<string, number[]>();
const sparkTries = new Map<string, number>();
const SPARK_TRIES = 3;

/** Closing prices of the last 20 sessions per ticker. A call that fails is tried again a couple
 *  of times (a slow or briefly unavailable API must not leave the column empty for good). */
export function useSparks(tickers: string[]): Record<string, number[]> {
  const [, bump] = useState(0);
  const [again, setAgain] = useState(0);
  const key = tickers.join(",");
  useEffect(() => {
    const want = key.split(",").filter((t) => t && !sparkCache.has(t) && (sparkTries.get(t) ?? 0) < SPARK_TRIES);
    if (!want.length) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    for (let i = 0; i < want.length; i += 60) {
      const batch = want.slice(i, i + 60);
      for (const t of batch) sparkTries.set(t, (sparkTries.get(t) ?? 0) + 1);
      api.sparks(batch, 20).then(
        (s) => {
          for (const t of batch) sparkCache.set(t, (s[t] ?? []).map((c) => c.close));
          if (live) bump((n) => n + 1);
        },
        () => {
          if (live && !timer) timer = setTimeout(() => setAgain((n) => n + 1), 2500);
        },
      );
    }
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [key, again]);
  return useMemo(
    () => Object.fromEntries(key.split(",").filter((t) => sparkCache.has(t)).map((t) => [t, sparkCache.get(t)!])),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the cache is filled as calls return
    [key, sparkCache.size],
  );
}

/** The 20-day lines of the rows that are on screen (and a screenful either side): a long table
 *  fetches as it is scrolled instead of drawing only its first rows. `watch(ticker)` is the ref of
 *  a row. Without IntersectionObserver (a test) every row counts as visible. */
export function useVisibleSparks(max = 600) {
  const [seen, setSeen] = useState<string[]>([]);
  const known = useRef(new Set<string>());
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const watcher = useRef<IntersectionObserver | null>(null);
  const flush = useCallback(() => {
    if (timer.current) return;
    timer.current = setTimeout(() => {
      timer.current = undefined;
      setSeen([...known.current]);
    }, 60);
  }, []);
  const add = useCallback(
    (ticker: string) => {
      if (known.current.has(ticker) || known.current.size >= max) return;
      known.current.add(ticker);
      flush();
    },
    [flush, max],
  );
  useEffect(
    () => () => {
      watcher.current?.disconnect();
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const watch = useCallback(
    (ticker: string) => (el: Element | null) => {
      if (!el || known.current.has(ticker)) return;
      if (typeof IntersectionObserver === "undefined") return add(ticker);
      watcher.current ??= new IntersectionObserver(
        (entries) => {
          for (const e of entries) {
            if (!e.isIntersecting) continue;
            const t = (e.target as HTMLElement).dataset.spark;
            if (t) add(t);
            watcher.current?.unobserve(e.target);
          }
        },
        { rootMargin: "400px 0px" },
      );
      (el as HTMLElement).dataset.spark = ticker;
      watcher.current.observe(el);
    },
    [add],
  );
  return { sparks: useSparks(seen), watch };
}

/** The columns a list can show (the symbol is always there); the default is all of them. */
export const LIST_COLUMNS = [
  ["grade", "Grade"],
  ["last", "Last"],
  ["chg_pct", "Change %"],
  ["spark", "20-day chart"],
  ["rvol", "RVOL"],
  ["setup", "Setup"],
] as const;
export type ListColumn = (typeof LIST_COLUMNS)[number][0];

export interface ListView {
  sort: Sort | null;
  hidden: ListColumn[];
}

const viewKey = (listId: string) => `list-view.${listId}`;

/** A list's own sort and visible columns, remembered per list in the browser (UX round 3). */
export function useListView(listId: string): {
  view: ListView;
  setSort: (s: Sort | null | ((s: Sort | null) => Sort | null)) => void;
  toggleColumn: (c: ListColumn) => void;
} {
  const [state, setState] = useState<{ id: string; view: ListView }>(() => ({
    id: listId,
    view: readPref<ListView>(viewKey(listId), { sort: null, hidden: [] }),
  }));
  // Another list: its own saved view (state is replaced during render, not in an effect)
  if (state.id !== listId) setState({ id: listId, view: readPref<ListView>(viewKey(listId), { sort: null, hidden: [] }) });
  const view = state.id === listId ? state.view : readPref<ListView>(viewKey(listId), { sort: null, hidden: [] });
  const save = (next: ListView) => {
    setState({ id: listId, view: next });
    writePref(viewKey(listId), next);
  };
  return {
    view,
    setSort: (s) => save({ ...view, sort: typeof s === "function" ? s(view.sort) : s }),
    toggleColumn: (c) =>
      save({ ...view, hidden: view.hidden.includes(c) ? view.hidden.filter((x) => x !== c) : [...view.hidden, c] }),
  };
}
