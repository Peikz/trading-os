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
});
