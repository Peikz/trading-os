import type { PositionCard } from "../../api";
import { holdDay, nextScanBits, reasonShort, whenOf } from "./model";

const pos = (extra: Partial<PositionCard> = {}): PositionCard => ({
  ticker: "ABCD", setup: "EP", direction: "long", shares: 10, entry_date: "2026-11-09", entry: 10,
  price: 11, move_pct: 1, open_r: 1, pnl: 10, to_stop_pct: 5, stop: 9, facts: [], ...extra,
});

describe("the calm layout's short lines", () => {
  it("shortens the market reasons to a few words", () => {
    expect(reasonShort("QQQ light is red.")).toBe("QQQ light red");
    expect(reasonShort("Heat is mild: 19 stocks up 50 %+ in a quarter (this band: x).")).toBe("Heat 19, mild");
    expect(reasonShort("IBD: uptrend under pressure (3 days).")).toBe("IBD uptrend under pressure");
    expect(reasonShort("Something else.")).toBe("Something else");
  });

  it("reads the next scan's New York and Copenhagen times", () => {
    expect(nextScanBits("Wed 04 Nov, 10:10 New York (16:10 in Copenhagen)")).toMatchObject({ day: "Wed 04 Nov", ny: "10:10", cph: "16:10" });
    expect(nextScanBits("soon").ny).toBeNull();
  });

  it("counts the day of a position: the plan's line first, else the weekdays held", () => {
    expect(holdDay(pos({ facts: ["Day 6 of 21: hold"] }))).toEqual({ day: 6, of: 21 });
    // Mon 9 Nov to Fri 13 Nov: the fifth day
    expect(holdDay(pos(), new Date("2026-11-13T15:00:00"))).toEqual({ day: 5, of: 21 });
  });

  it("writes the buy time on one line", () => {
    const row = {
      ticker: "ABCD", scan: "x", scan_label: "EP", grade: "A", run_label: "r", run_slot: "am", facts: [], stats: [], levels: {},
      decision: { text: "Buy at 10:30 New York", local: "16:30 in Copenhagen", session: null, day: null },
    };
    expect(whenOf({ key: "k", kind: "act", ticker: "ABCD", row })).toBe("Buy at 10:30 NY · 16:30 CPH");
    expect(whenOf({ key: "k", kind: "c", ticker: "ABCD", row: { ...row, grade: "C", decision: null } })).toBe("No tested edge");
  });
});
