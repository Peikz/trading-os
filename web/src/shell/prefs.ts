// Small remembered choices (UX round 3, 18 Nov 2026): the Chart's arrows and lines, the arrow keys
// setting, a list's sort and columns, the Today run. Browser storage only, every read and write
// wrapped in try/catch (a private window, blocked site data), and the page works without it.
// A change is announced in-page, so two places that show the same choice stay in step.
import { useCallback, useEffect, useState } from "react";

const PREFIX = "trading-os.";
const EVENT = "trading-os:pref";

export function readPref<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writePref<T>(key: string, value: T): void {
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    /* a private window: the choice lasts until the page closes */
  }
  try {
    window.dispatchEvent(new CustomEvent(EVENT, { detail: key }));
  } catch {
    /* no CustomEvent in this environment */
  }
}

/** A remembered value: `[value, set]`, shared by every component that uses the same key. */
export function usePref<T>(key: string, fallback: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => readPref(key, fallback));
  useEffect(() => {
    const on = (e: Event) => {
      if ((e as CustomEvent<string>).detail === key) setValue(readPref(key, fallback));
    };
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the fallback is a constant
  }, [key]);
  const set = useCallback(
    (v: T) => {
      setValue(v);
      writePref(key, v);
    },
    [key],
  );
  return [value, set];
}

/** The Chart's arrows and lines, one tap each (the Chart's symbol bar and the phone tools row). */
export const CHART_SHOW = { hits: true, fills: true, levels: true };
export type ChartShow = typeof CHART_SHOW;

/** The arrow keys, J and K step through the list (Settings). On unless switched off. */
export const useArrowKeys = () => usePref<boolean>("arrow-keys", true);
export const arrowKeysOn = () => readPref<boolean>("arrow-keys", true);

/** Show the manual test runs next to the scheduled ones (Settings). On unless switched off, as in
 * Streamlit; the API reads it from a header on every request. */
export const useManualRuns = () => usePref<boolean>("manual-runs", true);
export const manualRunsOn = () => readPref<boolean>("manual-runs", true);

/** The stocks of the Screener's last result, for the Chart's "Last screener result" list. */
export const LAST_SCREEN_KEY = "last-screen";
export const readLastScreen = () => readPref<string[]>(LAST_SCREEN_KEY, []);
export const writeLastScreen = (tickers: string[]) => writePref(LAST_SCREEN_KEY, tickers.slice(0, 200));
