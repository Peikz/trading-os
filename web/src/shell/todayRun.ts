// The scan runs of today and the one picked (UX round 3, 18 Nov 2026). Today, the Chart's "Today's
// hits" list and the Screener's Scan hits page share the pick: "all" (every run of the day,
// de-duplicated, each stock tagged with its runs) or one run's id. The pick lives in memory, so a
// reload starts on "All today" again.
import { useEffect, useState, useSyncExternalStore } from "react";
import { api, type TodayRuns } from "../api";

export const ALL = "all";
let picked = ALL;
const subscribers = new Set<() => void>();

export function pickRun(id: string): void {
  if (id === picked) return;
  picked = id;
  subscribers.forEach((f) => f());
}

export function useRunPick(): [string, (id: string) => void] {
  const id = useSyncExternalStore(
    (f) => {
      subscribers.add(f);
      return () => subscribers.delete(f);
    },
    () => picked,
  );
  return [id, pickRun];
}

export const getRunPick = () => picked;

/** The Chart's list id for the pick: "hits" for all of today, `run:ID` for one run. */
export const chartListOf = (id: string) => (id === ALL ? "hits" : `run:${id}`);

/** Today's runs (`/api/today-runs`), refreshed when new data is pulled. */
export function useTodayRuns(): TodayRuns | null {
  const [data, setData] = useState<TodayRuns | null>(null);
  useEffect(() => {
    const load = () => api.todayRuns().then((d) => setData(Array.isArray(d?.runs) ? d : null), () => setData(null));
    load();
    window.addEventListener("trading-os:refresh", load);
    return () => window.removeEventListener("trading-os:refresh", load);
  }, []);
  // A pick that is not one of today's runs (a new day) falls back to all of them
  useEffect(() => {
    if (data && picked !== ALL && !data.runs.some((r) => r.id === picked)) pickRun(ALL);
  }, [data]);
  return data;
}

/** The run's name with its time: `10:15 · 16:15 CPH`-style pieces for a label. */
export function runTimes(r: { ny: string | null; cph: string | null }): string {
  return r.ny ? `${r.ny} NY · ${r.cph} CPH` : "";
}
