// The scan runs of today and the one picked (UX round 3, 18 Nov 2026). Today, the Chart's "Today's
// hits" list and the Screener's Scan hits page share the pick: "all" (every run of the day,
// de-duplicated, each stock tagged with its runs) or one run's id. The pick lives in memory, so a
// reload starts on "All today" again.
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { api, type TodayRuns } from "../api";

export const ALL = "all";
/** An earlier day's run id: `2026-11-17_am` (the Run menu's "Earlier runs"). */
const EARLIER = /^\d{4}-\d{2}-\d{2}_[a-z]+$/;
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
  // A pick that is neither one of today's runs nor an earlier day's run falls back to all of them
  useEffect(() => {
    if (data && picked !== ALL && !data.runs.some((r) => r.id === picked) && !EARLIER.test(picked)) pickRun(ALL);
  }, [data]);
  return data;
}

/** The run's name with its time: `10:15 · 16:15 CPH`-style pieces for a label. */
export function runTimes(r: { ny: string | null; cph: string | null }): string {
  return r.ny ? `${r.ny} NY · ${r.cph} CPH` : "";
}

/** The scheduled runs of earlier days, newest first (the Run menu's "Earlier runs"): everything
 * the API lists that is not one of today's runs. */
export function useEarlierRuns(today: TodayRuns | null): { id: string; label: string }[] {
  const [all, setAll] = useState<{ id: string; label: string; session: string }[]>([]);
  useEffect(() => {
    const load = () =>
      api.runs().then(
        (rs) => setAll(rs.filter((r) => r.kind === "scheduled").map((r) => ({ id: r.id, label: r.label, session: r.session }))),
        () => setAll([]),
      );
    load();
    window.addEventListener("trading-os:refresh", load);
    return () => window.removeEventListener("trading-os:refresh", load);
  }, []);
  // The same list while nothing changed: a screen's filter bar rebuilds itself when this changes
  return useMemo(() => {
    const ids = new Set(today?.runs.map((r) => r.id) ?? []);
    return all.filter((r) => !ids.has(r.id) && (!today?.session || r.session < today.session)).slice(0, 40);
  }, [all, today]);
}
