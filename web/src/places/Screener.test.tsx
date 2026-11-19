import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { resetSymbols } from "../shell/symbols";
import { pickRun } from "../shell/todayRun";
import { Screener } from "./Screener";

const A = "WZQW";
const B = "XQZX";
const C = "VZQV";

const hit = (ticker: string, scan: string, grade: string, extra: Record<string, unknown> = {}) => ({
  ticker,
  scan,
  scan_label: scan === "ep" ? "EP 10:30" : "Breakout",
  grade,
  runs: ["am"],
  levels: { entry: 10, stop: 9 },
  close: 10,
  chg_pct: 3.2,
  rvol50: 2.1,
  adr20_pct: 5,
  plan_entry: 10,
  plan_stop: 9,
  grade_why: `Why ${ticker}`,
  ...extra,
});

const routes = () =>
  mockApi({
    "GET /api/today-runs": {
      session: "2026-11-18",
      all: { id: "all", label: "All today", count: 2 },
      runs: [
        { id: "2026-11-18_am", slot: "am", name: "10:15", ny: "10:17", cph: "16:17", count: 1 },
        { id: "2026-11-18_eod", slot: "eod", name: "End of day", ny: "16:17", cph: "22:17", count: 1 },
      ],
    },
    "GET /api/scan-hits": (url: string) => {
      const run = new URL(url, "http://x").searchParams.get("run");
      const rows = [hit(A, "ep", "A+"), hit(B, "bo", "B"), hit(C, "ep", "")];
      return {
        run,
        label: "All today",
        count: rows.length,
        scans: [{ id: "ep", label: "EP 10:30", count: 2 }, { id: "bo", label: "Breakout", count: 1 }],
        rows: run === "all" ? rows : rows.slice(0, 1),
      };
    },
    "GET /api/sparks": {},
    "GET /api/symbols": { asof: "2026-11-18", symbols: [[A, "Wizard Holdings"], [B, "Xylo Works"], [C, "Vortex Co"]] },
    "GET /api/chart/picks": [],
  });

describe("Screener, Scan hits", () => {
  beforeEach(() => {
    resetSymbols();
    pickRun("all");
    window.location.hash = "#/screener/hits";
  });

  it("lists every hit of all of today's runs and narrows by grade and by scan", async () => {
    routes();
    render(<Screener tab="hits" params={new URLSearchParams()} />);
    const table = await screen.findByRole("table", { name: "Results" });
    expect(within(table).getAllByRole("row")).toHaveLength(4); // header + three hits
    expect(screen.getByText("3 hits")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run\s*All today \(2\)/ })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Grade" })).getByRole("button", { name: "B" }));
    expect(screen.getByText("1 hit")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Grade" })).getByRole("button", { name: "All" }));
    fireEvent.click(screen.getByRole("button", { name: /Scan\s*All scans/ }));
    fireEvent.click(screen.getByRole("option", { name: /Breakout/ }));
    expect(screen.getByText("1 hit")).toBeInTheDocument();
  });

  it("shows a stock found by two scans once, with both setups and every run", async () => {
    mockApi({
      "GET /api/today-runs": { session: "2026-11-18", all: { id: "all", label: "All today", count: 2 }, runs: [] },
      "GET /api/scan-hits": {
        run: "all", label: "All today", count: 3,
        scans: [{ id: "ep", label: "EP 10:30", count: 2 }, { id: "bo", label: "Breakout", count: 1 }],
        rows: [hit(A, "ep", "A+", { runs: ["am"] }), hit(A, "bo", "B", { runs: ["eod", "am"] }), hit(B, "bo", "B")],
      },
      "GET /api/sparks": {},
      "GET /api/symbols": { asof: "2026-11-18", symbols: [] },
      "GET /api/chart/picks": [],
    });
    render(<Screener tab="hits" params={new URLSearchParams()} />);
    const table = await screen.findByRole("table", { name: "Results" });
    expect(within(table).getAllByRole("row")).toHaveLength(3); // header + two stocks, not three rows
    expect(screen.getByText("2 hits")).toBeInTheDocument();
    const first = within(table).getAllByRole("row")[1];
    expect(first).toHaveTextContent(A);
    expect(first).toHaveTextContent("EP 10:30 · Breakout");
    expect(first).toHaveTextContent("am · eod");
    // A single scan keeps its own rows
    fireEvent.click(screen.getByRole("button", { name: /Scan\s*All scans/ }));
    fireEvent.click(screen.getByRole("option", { name: /Breakout/ }));
    expect(screen.getByText("2 hits")).toBeInTheDocument();
  });

  it("previews the selected row with its entry and stop, and Enter opens it on the Chart", async () => {
    routes();
    render(<Screener tab="hits" params={new URLSearchParams()} />);
    await screen.findByRole("table", { name: "Results" });
    const preview = await screen.findByLabelText("Preview");
    expect(preview).toHaveTextContent(A); // the first row is selected at once
    expect(preview).toHaveTextContent("Why " + A);
    fireEvent.keyDown(window, { key: "ArrowDown" });
    await waitFor(() => expect(screen.getByLabelText("Preview")).toHaveTextContent(B));
    expect(screen.getByLabelText("Preview")).toHaveTextContent("Entry10.00");
    fireEvent.keyDown(window, { key: "Enter" });
    expect(window.location.hash).toContain(`#/chart?s=${B}`);
  });

  it("asks for one run when it is picked from the Run menu", async () => {
    const calls = routes();
    render(<Screener tab="hits" params={new URLSearchParams()} />);
    await screen.findByRole("table", { name: "Results" });
    fireEvent.click(screen.getByRole("button", { name: /Run\s*All today/ }));
    fireEvent.click(screen.getByRole("option", { name: /10:15/ }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("run=2026-11-18_am"))).toBe(true));
  });
});
