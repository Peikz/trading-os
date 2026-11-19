// The Chart's lists: the picker's catalog, one list's rows (sortable), and the 20-day sparklines
// (one `/api/sparks` call per 60 stocks, kept for the visit so a list you come back to is
// drawn at once).
import { useEffect, useMemo, useState } from "react";
import { api, type ChartList, type ChartListInfo, type ChartListRow } from "../../api";
import { readPref, writePref } from "../../shell/prefs";

export function useChartLists(): ChartListInfo[] | null {
  const [lists, setLists] = useState<ChartListInfo[] | null>(null);
  useEffect(() => {
    const load = () => api.chartLists().then((r) => setLists(r.lists), () => setLists([]));
    load();
    window.addEventListener("trading-os:refresh", load);
    return () => window.removeEventListener("trading-os:refresh", load);
  }, []);
  return lists;
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
      api.chartList(id).then(
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

/** Closing prices of the last 20 sessions per ticker. */
export function useSparks(tickers: string[]): Record<string, number[]> {
  const [, bump] = useState(0);
  const key = tickers.join(",");
  useEffect(() => {
    const want = key.split(",").filter((t) => t && !sparkCache.has(t));
    if (!want.length) return;
    let live = true;
    for (let i = 0; i < want.length; i += 60) {
      const batch = want.slice(i, i + 60);
      api.sparks(batch, 20).then(
        (s) => {
          for (const t of batch) sparkCache.set(t, (s[t] ?? []).map((c) => c.close));
          if (live) bump((n) => n + 1);
        },
        () => {},
      );
    }
    return () => {
      live = false;
    };
  }, [key]);
  return useMemo(
    () => Object.fromEntries(key.split(",").filter((t) => sparkCache.has(t)).map((t) => [t, sparkCache.get(t)!])),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the cache is filled as calls return
    [key, sparkCache.size],
  );
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
