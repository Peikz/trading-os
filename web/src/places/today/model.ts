// What Today's views share: the queue's items (a scan hit, a position, a watched stock), the words
// of the title line, and what a view needs from an item (its price, change, lines and key facts).
import type { BoardRow, PositionCard, Stat } from "../../api";

export type Kind = "push" | "act" | "c" | "position" | "watch";
export interface Item {
  key: string;
  kind: Kind;
  ticker: string;
  row?: BoardRow;
  pos?: PositionCard;
}

export type View = "Focus" | "Grid" | "List";
export const VIEWS: View[] = ["Focus", "Grid", "List"];

/** What the "Show" menu lists: today's queue, or one list of stocks (round 4, Streamlit's Show). */
export const SCOPE_TODAY = "today";
export const SCOPE_PUSHED = "pushed";
export const SCOPE_ALL = "all";
export const SCOPE_LIST = "wl:";
export const SCOPE_LABELS: Record<string, string> = {
  [SCOPE_TODAY]: "Today's list",
  [SCOPE_PUSHED]: "Pushed, incl. C",
  [SCOPE_ALL]: "Every scan hit",
};
export const scopeLabel = (scope: string) =>
  scope.startsWith(SCOPE_LIST) ? scope.slice(SCOPE_LIST.length) : (SCOPE_LABELS[scope] ?? scope);

/** The push link's stocks (`?t=A,B`), as the Streamlit board reads them. */
export function pushTickers(search: string): string[] {
  const t = new URLSearchParams(search).get("t") ?? "";
  return t
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

/** The screen a "Flip through on Today" link came from (`?screen=Name&t=A,B`). */
export function screenName(search: string): string | null {
  return new URLSearchParams(search).get("screen") || null;
}

/** The query of a Today link: the page's own (`/?push=am&t=A,B`, a push link) and the hash's
 * (`#/today?screen=Name&t=A,B`, the Screener's "Flip through on Today"); the hash wins. */
export function todayQuery(location: Pick<Location, "search" | "hash">): string {
  const own = new URLSearchParams(location.search);
  const hash = location.hash.includes("?") ? new URLSearchParams(location.hash.split("?")[1]) : new URLSearchParams();
  hash.forEach((v, k) => own.set(k, v));
  const out = own.toString();
  return out ? `?${out}` : "";
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** "2 setups to act on · 1 position · 2 on watch" */
export function titleLine(act: number, positions: number, watch: number): string {
  return [
    act ? `${plural(act, "setup")} to act on` : "Nothing to act on",
    plural(positions, "position"),
    `${watch} on watch`,
  ].join(" · ");
}

export function rowItem(kind: Kind, r: BoardRow): Item {
  return { key: `${kind}:${r.ticker}:${r.scan}`, kind, ticker: r.ticker, row: r };
}

export function sectorOf(row: BoardRow): string {
  return typeof row.industry === "string" ? row.industry : typeof row.sector === "string" ? row.sector : "";
}

export function priceOf(i: Item): number | null {
  if (i.pos) return i.pos.price;
  return typeof i.row?.close === "number" ? (i.row.close as number) : null;
}

export function changeOf(i: Item): number | null {
  if (i.pos) return i.pos.move_pct;
  return typeof i.row?.chg_pct === "number" ? i.row.chg_pct : null;
}

export function levelsOf(i: Item): Record<string, number> {
  if (i.row) return i.row.levels ?? {};
  const out: Record<string, number> = {};
  if (i.pos?.entry) out.entry = i.pos.entry;
  if (i.pos?.stop) out.stop = i.pos.stop;
  return out;
}

export function alertOf(i: Item): number {
  if (i.pos) return i.pos.stop ?? i.pos.entry;
  return typeof i.row?.alert_default === "number" ? (i.row.alert_default as number) : 0;
}

export function statsOf(i: Item): Stat[] {
  if (i.row) return i.row.stats ?? [];
  const p = i.pos!;
  return [
    { label: "Shares", value: p.shares.toLocaleString("en-US") },
    { label: "Entry", value: p.entry.toFixed(2) },
    { label: "In since", value: p.entry_date },
    { label: "Stop", value: p.stop === null ? "no stop" : p.stop.toFixed(2) },
    { label: "To stop", value: p.to_stop_pct === null ? "–" : `${p.to_stop_pct.toFixed(1)}%` },
  ];
}

export const GRADES = ["A+++", "A++", "A+", "A", "B", "C"];

/** The chart's anchor day for the AVWAP line: the hit's own, else the run's session. */
export const anchorOf = (i: Item): string | null =>
  (i.row?.avwap_anchor as string | null | undefined) ?? (i.row?.run_session as string | null | undefined) ?? null;
