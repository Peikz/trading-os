// The notebook's entries, search, tag counts, linked mentions and addresses. Synthetic notes.
import type { NbIndex } from "../api";
import { entriesOf, mentionsOf, newestFirst, parseSelection, search, tagCounts } from "./model";
import { wikiTarget } from "./env";

const T = ["W", "Z", "Q", "W"].join("");

const index: NbIndex = {
  today: "2026-11-19",
  daily: [
    { id: "d1", date: "2026-11-18", text: `Calm. $${T} held. #tone`, stocks: [T], tags: ["tone"] },
    { id: "d2", date: "2026-11-16", text: "Chop #tone #ep", stocks: [], tags: ["tone", "ep"] },
  ],
  trades: [
    {
      id: "t1", status: "closed", ticker: T, direction: "long", entry_date: "2026-11-02", exit_date: "2026-11-09",
      setup: "ep_day", r: 2, pnl: 100, entry: 10, exit: 12, stop: 9, grade: "A", conviction: 2,
      text: "Clean breakout #ep", tags: ["late", "ep"], typed_tags: ["late"],
    },
  ],
  stocks: [{ ticker: T, notes: [{ note_id: "n1", date: "2026-11-05", text: "Flag forming #watch", tags: ["watch"] }], tags: ["watch"] }],
  pages: [
    { slug: "plan", title: "Weekly plan", created: "2026-11-01", updated: "2026-11-17", text: `Review [[2026-11-18]] and [[${T}]]`, tags: [], typed_tags: [] },
    { slug: "rules", title: "Rules", created: "2026-11-01", updated: "2026-11-10", text: "See [[Weekly plan]]", tags: ["rules"], typed_tags: ["rules"] },
  ],
  tags: [],
  tickers: [T],
};

describe("the notebook as entries", () => {
  const entries = entriesOf(index);

  it("has an entry for every day, trade, stock note and page, each with its address", () => {
    expect(entries.map((e) => e.ref).sort()).toEqual(
      [`daily:d1`, `daily:d2`, `trade:t1`, `stock:${T}`, `page:plan`, `page:rules`].sort(),
    );
    expect(entries.find((e) => e.ref === "daily:d1")!.title).toMatch(/18 November 2026/);
  });

  it("counts a tag once per entry that carries it, A to Z", () => {
    expect(tagCounts(entries)).toEqual([
      { tag: "ep", count: 2 }, { tag: "late", count: 1 }, { tag: "rules", count: 1 }, { tag: "tone", count: 2 }, { tag: "watch", count: 1 },
    ]);
  });

  it("searches titles, text, #tags and $stocks, every word, newest first", () => {
    expect(search(entries, "breakout").map((e) => e.ref)).toEqual(["trade:t1"]);
    expect(search(entries, "#tone").map((e) => e.ref)).toEqual(["daily:d1", "daily:d2"]);
    expect(search(entries, `$${T.toLowerCase()} held`).map((e) => e.ref)).toEqual(["daily:d1"]);
    expect(search(entries, "   ")).toEqual([]);
    expect(search(entries, "nothing like this")).toEqual([]);
    const all = entries.slice().sort(newestFirst);
    expect(all[0].date >= all[all.length - 1].date).toBe(true);
  });

  it("finds the notes that link to a page, a day or a stock", () => {
    expect(mentionsOf(entries, { kind: "page", key: "Weekly plan", self: "page:plan" }).map((e) => e.ref)).toEqual(["page:rules"]);
    expect(mentionsOf(entries, { kind: "day", key: "2026-11-18" }).map((e) => e.ref)).toEqual(["page:plan"]);
    const stock = mentionsOf(entries, { kind: "stock", key: T }).map((e) => e.ref);
    expect(stock).toEqual(expect.arrayContaining(["daily:d1", "trade:t1", "page:plan"]));
    expect(stock).not.toContain(`stock:${T}`); // the stock's own notes are not mentions
  });
});

describe("addresses", () => {
  it("reads ?p= as a selection", () => {
    expect(parseSelection(null)).toBeNull();
    expect(parseSelection("today")).toEqual({ kind: "today" });
    expect(parseSelection("daily:d1")).toEqual({ kind: "daily", id: "d1" });
    expect(parseSelection("day:2026-11-18")).toEqual({ kind: "day", date: "2026-11-18" });
    expect(parseSelection("trade:open-ABC-2026-11-01")).toEqual({ kind: "trade", id: "open-ABC-2026-11-01" });
    expect(parseSelection(`stock:${T.toLowerCase()}`)).toEqual({ kind: "stock", ticker: T });
    expect(parseSelection("tag:Ep")).toEqual({ kind: "tag", tag: "ep" });
    expect(parseSelection("new:A new page")).toEqual({ kind: "new", title: "A new page" });
    expect(parseSelection("day:nope")).toBeNull();
    expect(parseSelection("page:")).toBeNull();
  });

  it("sends a [[wiki link]] to a stock, a day, an existing page or a new page", () => {
    const pages = [{ slug: "plan", title: "Weekly plan" }];
    expect(wikiTarget(T, pages)).toBe(`stock:${T}`);
    expect(wikiTarget("2026-11-18", pages)).toBe("day:2026-11-18");
    expect(wikiTarget("weekly PLAN", pages)).toBe("page:plan");
    expect(wikiTarget("Something else", pages)).toBe("new:Something else");
  });
});
