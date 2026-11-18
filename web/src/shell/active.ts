// The one active stock (UX round 1, 18 Nov 2026): every panel follows it. It lives in this small
// store and, on the Chart, in the address (`#/chart?s=TICKER&list=ID`), so a link, a reload and
// the back button all keep it. `list` is the list that last had focus: the one the arrow keys
// and the arrows in the header step through.
import { useSyncExternalStore } from "react";
import { hrefFor, parseHash, stockLink } from "../routes";

export interface Active {
  symbol: string;
  list: string;
}

let state: Active = { symbol: "", list: "" };
const subscribers = new Set<() => void>();

const clean = (t: string) => t.trim().replace(/^\$/, "").toUpperCase();

function set(next: Active) {
  if (next.symbol === state.symbol && next.list === state.list) return;
  state = next;
  subscribers.forEach((f) => f());
}

export function getActive(): Active {
  return state;
}

export function useActive(): Active {
  return useSyncExternalStore(
    (f) => {
      subscribers.add(f);
      return () => subscribers.delete(f);
    },
    () => state,
  );
}

/** Take the stock and list from an address's query (`s`, or the old `t`; `list`). */
export function syncFromRoute(params: URLSearchParams): void {
  const s = params.get("s") ?? params.get("t");
  if (s === null && !params.has("list")) return;
  set({ symbol: s !== null ? clean(s) : state.symbol, list: params.get("list") ?? state.list });
}

/** Make `symbol` the active stock. On the Chart this rewrites the address in place (no new
 * history entry per step); elsewhere it only remembers the stock. */
export function setActive(symbol: string, list?: string): void {
  set({ symbol: clean(symbol), list: list ?? state.list });
  const route = parseHash(window.location.hash);
  if (route.place !== "chart") return;
  const params = new URLSearchParams({ s: state.symbol });
  if (state.list) params.set("list", state.list);
  route.params.forEach((v, k) => {
    if (!["s", "t", "list"].includes(k)) params.set(k, v);
  });
  window.history.replaceState(null, "", hrefFor("chart", "", params));
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

/** Open a stock on the Chart (a new history entry). */
export function openChart(symbol: string, list?: string): void {
  const t = clean(symbol);
  set({ symbol: t, list: list ?? state.list });
  window.location.hash = stockLink(t, state.list || undefined);
}

/** The Chart's address with the active stock, for the top bar's link. */
export function chartHref(a: Active = state): string {
  return a.symbol ? stockLink(a.symbol, a.list || undefined) : hrefFor("chart");
}
