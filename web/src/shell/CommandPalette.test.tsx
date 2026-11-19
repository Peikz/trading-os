import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { CommandPalette } from "./CommandPalette";
import { resetSymbols } from "./symbols";

const A = "WZQW";
const B = "XQZX";

describe("Search that filters as you type", () => {
  beforeEach(() => {
    resetSymbols();
    mockApi({
      "GET /api/symbols": { asof: "x", symbols: [[A, "Wizard Holdings"], [B, "Wizard Works Inc."], ["VZQV", "Quartz Co"]] },
      "GET /api/chart/picks": [{ ticker: A, where: "Today's hits" }],
      "GET /api/chart-lists/hits": { id: "hits", label: "Today's hits", rows: [{ ticker: A, grade: "A+", setup: "EP", last: 1, chg_pct: 1, rvol: 1, signal_id: null }] },
    });
  });
  const open = () => {
    render(<CommandPalette onClose={() => {}} onPull={() => {}} onPush={() => {}} />);
    return screen.getByLabelText("Search stocks, pages and tabs", { selector: "input" });
  };

  it("lists tickers that start with the text, then company names, with grade and list", async () => {
    const input = open();
    fireEvent.change(input, { target: { value: "wz" } });
    const list = await screen.findByRole("listbox", { name: "Results" });
    await waitFor(() => expect(within(list).getAllByRole("option")[0]).toHaveTextContent(`${A}Wizard HoldingsA+Today's hits`));
    fireEvent.change(input, { target: { value: "wizard" } });
    await waitFor(() => expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual(expect.arrayContaining([expect.stringContaining(B)])));
  });

  it("opens the stock on the Chart with the arrows and Enter", async () => {
    const input = open();
    fireEvent.change(input, { target: { value: "wizard" } });
    await screen.findByText(B);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(window.location.hash).toContain(`#/chart?s=${B}`);
  });

  it("says so when no stock matches", async () => {
    const input = open();
    fireEvent.change(input, { target: { value: "qqqqqq" } });
    expect(await screen.findByText("No stock matches")).toBeInTheDocument();
  });

  it("shows a ticker's scan hits, lists and notes, and words in the notes and the guide", async () => {
    mockApi({
      "GET /api/symbols": { asof: "x", symbols: [[A, "Wizard Holdings"]] },
      "GET /api/chart/picks": [],
      "GET /api/chart-lists/hits": { id: "hits", label: "Today's hits", rows: [] },
      "GET /api/known/": { ticker: A, known: true },
      "GET /api/search/ticker/": {
        ticker: A,
        runs_searched: 30,
        hits: [{ run: "2026-10-30 eod", scan: "EP after hours", tier: "alert", grade: "A", why: "5 points", points: "x" }],
        places: ["your list Leaders", "an open position"],
        notes: [{ date: "2026-10-29", kind: "stock note", text: "a base forming" }],
      },
      "GET /api/search/words": {
        q: A,
        stock: [{ ticker: A, date: "2026-10-29", text: "a base forming" }],
        daily: [],
        journal: [{ kind: "trade", ref_id: "t1", text: "held too long" }],
        guide: [{ section: "Grades", line: "A grade is a count of points" }],
      },
    });
    const input = open();
    fireEvent.change(input, { target: { value: A } });
    const detail = await screen.findByRole("region", { name: `${A} everywhere` });
    expect(within(detail).getByText(/last 30 runs/)).toBeInTheDocument();
    expect(within(detail).getByText("EP after hours")).toBeInTheDocument();
    expect(within(detail).getByText(/your list Leaders, an open position/)).toBeInTheDocument();
    const words = await screen.findByRole("region", { name: "Words in your notes and the guide" });
    expect(within(words).getByText(/held too long/)).toBeInTheDocument();
    expect(within(words).getByText("Grades")).toBeInTheDocument();
  });

  it("opens an exact ticker only the daily bars know, and says when a ticker does not exist", async () => {
    mockApi({
      "GET /api/symbols": { asof: "x", symbols: [[A, "Wizard Holdings"]] },
      "GET /api/chart/picks": [],
      "GET /api/chart-lists/hits": { id: "hits", label: "Today's hits", rows: [] },
      "GET /api/known/ETFZ": { ticker: "ETFZ", known: true },
      "GET /api/known/NOPEZ": { ticker: "NOPEZ", known: false },
    });
    const input = open();
    fireEvent.change(input, { target: { value: "etfz" } });
    await screen.findByText("In the data repo");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(window.location.hash).toContain("#/chart?s=ETFZ");
    fireEvent.change(input, { target: { value: "nopez" } });
    expect(await screen.findByText("NOPEZ is not in the universe")).toBeInTheDocument();
  });
});

