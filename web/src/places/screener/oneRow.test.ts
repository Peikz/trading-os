import type { ScanHit } from "../../api";
import { onePerStock } from "./oneRow";

const hit = (ticker: string, scan: string, label: string, grade: string, runs: string[]): ScanHit => ({
  ticker, scan, scan_label: label, grade, runs, levels: {},
});
const T = ["W", "Z", "Q", "W"].join("");
const U = ["X", "Z", "Q", "X"].join("");

describe("one row per stock under All scans", () => {
  it("keeps the best grade's row, joins the setups and lists every run in the order they ran", () => {
    const rows = [
      hit(T, "ep_am", "EP 10:30", "A+", ["eod", "am"]),
      hit(U, "bo", "Breakout", "B", ["am"]),
      hit(T, "ep9m", "EP9M pace", "B", ["am", "pm"]),
      hit(T, "ep_am", "EP 10:30", "A+", ["ah"]),
    ];
    const out = onePerStock(rows);
    expect(out.map((r) => r.ticker)).toEqual([T, U]);
    expect(out[0]).toMatchObject({ grade: "A+", scan: "ep_am", scan_label: "EP 10:30 · EP9M pace", runs: ["pm", "am", "eod", "ah"] });
    expect(out[1].scan_label).toBe("Breakout");
  });

  it("does not change the rows it is given", () => {
    const rows = [hit(T, "a", "A", "A", ["am"]), hit(T, "b", "B", "B", ["eod"])];
    onePerStock(rows);
    expect(rows[0].runs).toEqual(["am"]);
    expect(rows[0].scan_label).toBe("A");
  });
});
