// The notebook as one list of entries (a day, a trade, a stock's note, a page) built from
// `/api/notebook`, so search, tags and linked mentions work the same on all of them. Pure.
import type { NbIndex, NbTrade } from "../api";
import { DATE } from "./env";
import { cashtags, hashtags, isTicker, snippet, wikilinks } from "./text";

export type Kind = "daily" | "trade" | "stock" | "page";

export interface Entry {
  /** The notebook address of the page it opens: `daily:<id>`, `trade:<id>`, `stock:<T>`, `page:<slug>` */
  ref: string;
  kind: Kind;
  title: string;
  /** The day it is about or was last saved (newest first sorts on this) */
  date: string;
  text: string;
  tags: string[];
  stocks: string[];
}

export function dayTitle(day: string): string {
  const d = new Date(`${day}T12:00:00`);
  if (Number.isNaN(d.getTime())) return day;
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

export function tradeTitle(t: Pick<NbTrade, "ticker" | "entry_date" | "exit_date" | "status">): string {
  const to = t.exit_date ? ` → ${t.exit_date}` : " (open)";
  return `${t.ticker} ${t.entry_date ?? ""}${to}`.trim();
}

export function entriesOf(index: NbIndex): Entry[] {
  const out: Entry[] = [];
  for (const d of index.daily) {
    out.push({
      ref: `daily:${d.id}`, kind: "daily", title: dayTitle(d.date), date: d.date, text: d.text,
      tags: d.tags, stocks: [...new Set([...d.stocks, ...cashtags(d.text)])],
    });
  }
  for (const t of index.trades) {
    out.push({
      ref: `trade:${t.id}`, kind: "trade", title: tradeTitle(t), date: t.exit_date ?? t.entry_date ?? "",
      text: t.text, tags: t.tags, stocks: [t.ticker],
    });
  }
  for (const s of index.stocks) {
    for (const n of s.notes) {
      out.push({
        ref: `stock:${s.ticker}`, kind: "stock", title: `$${s.ticker}`, date: n.date, text: n.text,
        tags: n.tags, stocks: [s.ticker],
      });
    }
  }
  for (const p of index.pages) {
    out.push({
      ref: `page:${p.slug}`, kind: "page", title: p.title, date: p.updated, text: p.text, tags: p.tags,
      stocks: [...cashtags(p.text), ...wikilinks(p.text).filter(isTicker)],
    });
  }
  return out;
}

export const newestFirst = (a: Entry, b: Entry) => b.date.localeCompare(a.date) || a.title.localeCompare(b.title);

/** Tags with how many entries carry them, A to Z. */
export function tagCounts(entries: Entry[]): { tag: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const e of entries) for (const t of new Set(e.tags)) counts.set(t, (counts.get(t) ?? 0) + 1);
  return [...counts].map(([tag, count]) => ({ tag, count })).sort((a, b) => a.tag.localeCompare(b.tag));
}

export function search(entries: Entry[], query: string): Entry[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const words = q.split(/\s+/);
  return entries
    .filter((e) => {
      const hay = `${e.title} ${e.text} ${e.tags.map((t) => `#${t}`).join(" ")} ${e.stocks.map((s) => `$${s}`).join(" ")}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    })
    .sort(newestFirst);
}

export { snippet };

/** The notes that link to a page: `[[Title]]` for a page, `[[2026-11-19]]` for a day, `$T` or
 *  `[[T]]` for a stock (the stock's own notes left out). */
export function mentionsOf(entries: Entry[], target: { kind: Kind | "day"; key: string; self?: string }): Entry[] {
  const key = target.key;
  return entries
    .filter((e) => {
      if (e.ref === target.self) return false;
      if (target.kind === "stock") return e.kind !== "stock" && e.stocks.includes(key.toUpperCase());
      const links = wikilinks(e.text).map((l) => l.toLowerCase());
      return links.includes(key.toLowerCase());
    })
    .sort(newestFirst);
}

export type Selection =
  | { kind: "today" }
  | { kind: "day"; date: string }
  | { kind: "daily"; id: string }
  | { kind: "trade"; id: string }
  | { kind: "stock"; ticker: string }
  | { kind: "page"; slug: string }
  | { kind: "tag"; tag: string }
  | { kind: "new"; title: string }
  | null;

/** The address in `?p=` as a selection. */
export function parseSelection(p: string | null): Selection {
  if (!p) return null;
  if (p === "today") return { kind: "today" };
  const at = p.indexOf(":");
  if (at < 0) return null;
  const head = p.slice(0, at);
  const rest = p.slice(at + 1);
  if (!rest) return null;
  if (head === "day" && DATE.test(rest)) return { kind: "day", date: rest };
  if (head === "daily") return { kind: "daily", id: rest };
  if (head === "trade") return { kind: "trade", id: rest };
  if (head === "stock") return { kind: "stock", ticker: rest.toUpperCase() };
  if (head === "page") return { kind: "page", slug: rest };
  if (head === "tag") return { kind: "tag", tag: rest.toLowerCase() };
  if (head === "new") return { kind: "new", title: rest };
  return null;
}

export const monthOf = (day: string) => day.slice(0, 7);

export function monthTitle(month: string): string {
  const d = new Date(`${month}-15T12:00:00`);
  return Number.isNaN(d.getTime()) ? month : d.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

export { hashtags };
