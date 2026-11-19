// The stock universe's tickers and company names (`/api/symbols`, UX round 3, 18 Nov 2026): one
// small call per visit, kept in memory. `matchSymbols` is the search that filters as you type:
// a ticker that starts with the text first, then a ticker that contains it, then company names,
// at most `max` rows. A stock outside the universe is not found.
import { useEffect, useState } from "react";
import { api } from "../api";

export interface Symbol {
  ticker: string;
  name: string;
}

let cache: Symbol[] | null = null;
let pending: Promise<Symbol[]> | null = null;
const byTicker = new Map<string, string>();

function load(): Promise<Symbol[]> {
  if (cache) return Promise.resolve(cache);
  pending ??= api.symbols().then(
    (r) => {
      cache = (Array.isArray(r?.symbols) ? r.symbols : []).map(([ticker, name]) => ({ ticker, name }));
      byTicker.clear();
      for (const s of cache) byTicker.set(s.ticker, s.name);
      return cache;
    },
    () => {
      pending = null; // try again next time
      return [] as Symbol[];
    },
  );
  return pending;
}

/** The universe; null until it has loaded, an empty list when the API has none. */
export function useSymbols(): Symbol[] | null {
  const [list, setList] = useState<Symbol[] | null>(cache);
  useEffect(() => {
    let live = true;
    load().then((l) => live && setList(l));
    return () => {
      live = false;
    };
  }, []);
  return list;
}

/** A company's name by ticker, "" when unknown (or the universe has not loaded). */
export function nameOf(ticker: string): string {
  return byTicker.get(ticker.toUpperCase()) ?? "";
}

/** A hook that re-renders when the names arrive, then answers `nameOf`. */
export function useNames(): (ticker: string) => string {
  useSymbols();
  return nameOf;
}

export function matchSymbols(list: Symbol[], text: string, max = 20): Symbol[] {
  const q = text.trim().replace(/^\$/, "").toLowerCase();
  if (!q) return [];
  const starts: Symbol[] = [];
  const named: Symbol[] = [];
  for (const s of list) {
    const t = s.ticker.toLowerCase();
    if (t === q) starts.unshift(s);
    else if (t.startsWith(q)) starts.push(s);
    else if (s.name && s.name.toLowerCase().includes(q)) named.push(s);
  }
  const wordStart = (s: Symbol) => (s.name.toLowerCase().startsWith(q) ? 0 : 1);
  named.sort((a, b) => wordStart(a) - wordStart(b));
  return [...starts, ...named].slice(0, max);
}

/** Test hook: forget the loaded universe. */
export function resetSymbols(): void {
  cache = null;
  pending = null;
  byTicker.clear();
}
