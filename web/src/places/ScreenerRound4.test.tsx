// Round 4 on the Screener: a TradingView link per row, the scan's own table (its columns and the
// A+/A/B blocks) when one scan is picked, and from a screen "Flip through on Today" and the
// Chart's "Last screener result". Synthetic tickers, built from letters.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readLastScreen } from "../shell/prefs";
import { resetSymbols } from "../shell/symbols";
import { pickRun } from "../shell/todayRun";
import { mockApi } from "../test/mockApi";
import { Screener } from "./Screener";

const A = "WZQW";
const B = "XQZX";

const hit = (ticker: string, scan: string, grade: string) => ({
  ticker, scan, scan_label: scan === "ep" ? "EP 10:30" : "Breakout", grade, runs: ["eod"], levels: {},
  close: 10, chg_pct: 3.2, rvol50: 2.1, adr20_pct: 5, grade_why: `Why ${ticker}`,
  tv: `https://www.tradingview.com/chart/?symbol=NASDAQ%3A${ticker}`,
});

const scanTable = {
  run: "2026-11-18_eod",
  label: "2026-11-18 · eod",
  scans: [
    {
      scan: "ep", label: "EP 10:30", shown: 1, total: 1,
      columns: [
        { header: "Ticker", key: "ticker", fmt: "text" },
        { header: "Gap %", key: "gap_pct", fmt: "signed1" },
        { header: "Pace", key: "proj_volume", fmt: "shares" },
      ],
      rows: [{ ticker: A, gap_pct: 14.2, proj_volume: 2_500_000 }],
      blocks: [{ ticker: A, title: "Study A+ · 5 quality points", lines: ["Buy 10.00 · stop 9.00 (day low)", "Why: earnings reaction"] }],
      facts: [], charts: [],
    },
  ],
};

describe("Screener, round 4", () => {
  beforeEach(() => {
    resetSymbols();
    pickRun("all");
    window.localStorage.clear();
    window.location.hash = "#/screener/hits";
  });

  it("links every row to TradingView, and a picked scan gets its own table and the grade blocks", async () => {
    const calls = mockApi({
      "GET /api/today-runs": {
        session: "2026-11-18", all: { id: "all", label: "All today", count: 1 },
        runs: [{ id: "2026-11-18_eod", slot: "eod", name: "End of day", ny: "16:17", cph: "22:17", count: 1 }],
      },
      "GET /api/runs": [
        { id: "2026-11-18_eod", label: "2026-11-18 · eod", session: "2026-11-18", slot: "eod", kind: "scheduled" },
        { id: "2026-11-17_eod", label: "2026-11-17 · eod", session: "2026-11-17", slot: "eod", kind: "scheduled" },
      ],
      "GET /api/scan-hits": {
        run: "all", label: "All today", count: 2,
        scans: [{ id: "ep", label: "EP 10:30", count: 1 }, { id: "bo", label: "Breakout", count: 1 }],
        rows: [hit(A, "ep", "A+"), hit(B, "bo", "B")],
      },
      "GET /api/scan-tables": scanTable,
      "GET /api/sparks": {},
      "GET /api/symbols": { asof: "2026-11-18", symbols: [] },
      "GET /api/chart/picks": [],
    });
    render(<Screener tab="hits" params={new URLSearchParams()} />);
    const table = await screen.findByRole("table", { name: "Results" });
    expect(within(table).getAllByRole("link", { name: /on TradingView/ })).toHaveLength(2);
    expect(within(table).getByRole("link", { name: `${A} on TradingView` })).toHaveAttribute("href", expect.stringContaining(`NASDAQ%3A${A}`));
    expect(screen.queryByRole("tab", { name: "Scan table" })).not.toBeInTheDocument(); // all scans: no scan table
    // the Run menu reaches earlier days
    fireEvent.click(screen.getByRole("button", { name: /Run\s*All today/ }));
    expect(screen.getByRole("option", { name: "2026-11-17 · eod" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: /All today/ }));
    fireEvent.click(screen.getByRole("button", { name: /Scan\s*All scans/ }));
    fireEvent.click(screen.getByRole("option", { name: /EP 10:30/ }));
    // the blocks sit under the table
    const blocks = await screen.findByLabelText("A+, A and B hits as the push shows them");
    expect(blocks).toHaveTextContent("Study A+ · 5 quality points");
    expect(calls.some((c) => c.url === "/api/scan-tables?run=2026-11-18_eod&scan=ep")).toBe(true);
    fireEvent.click(screen.getByRole("tab", { name: "Scan table" }));
    const own = await screen.findByRole("region", { name: "EP 10:30 table" });
    expect(within(own).getByRole("columnheader", { name: "Gap %" })).toBeInTheDocument();
    expect(within(own).getByText("+14.2")).toBeInTheDocument();
    expect(within(own).getByText("2.5M")).toBeInTheDocument();
  });

  it("from a screen: opens a stock with the last result as the Chart's list, and flips through on Today", async () => {
    window.location.hash = "#/screener/screen";
    mockApi({
      "GET /api/screener/meta": { fields: {}, ops: { text: [], num: [], pct: [], money: [], bool: [] }, shown: [], examples: {}, saved: {}, labels: {} },
      "POST /api/screener/run": {
        count: 2, when: "the 18 Nov close", summary: "no filters: every stock", columns: ["ticker"], rows: [{ ticker: A, close: 10 }, { ticker: B, close: 20 }],
        tickers: [A, B], tv_list: "", signal_ids: {}, tv: { [A]: `https://www.tradingview.com/chart/?symbol=NASDAQ%3A${A}`, [B]: "https://www.tradingview.com/chart/?symbol=B" },
      },
      "GET /api/sparks": {},
      "GET /api/symbols": { asof: "2026-11-18", symbols: [] },
      "GET /api/chart/picks": [],
    });
    render(<Screener tab="screen" params={new URLSearchParams()} />);
    const table = await screen.findByRole("table", { name: "Results" });
    expect(within(table).getByRole("link", { name: `${B} on TradingView` })).toHaveAttribute("href", "https://www.tradingview.com/chart/?symbol=B");
    fireEvent.click(await screen.findByRole("button", { name: "Flip through on Today" }));
    expect(decodeURIComponent(window.location.hash)).toBe(`#/today?screen=Screener&t=${A},${B}`);
    window.location.hash = "#/screener/screen";
    fireEvent.doubleClick(within(table).getByText(B));
    await waitFor(() => expect(window.location.hash).toContain(`#/chart?s=${B}&list=screen`));
    expect(readLastScreen()).toEqual([A, B]);
  });
});
