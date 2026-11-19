import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { resetSymbols } from "../shell/symbols";
import { Watchlists } from "./Watchlists";

const A = "WZQW";
const B = "XQZX";

const list = {
  name: "Mine",
  label: "the 18 Nov close",
  columns: ["ticker", "close", "chg_pct", "rvol50", "note", "added"],
  rows: [
    { ticker: A, close: 10.5, chg_pct: 2.5, rvol50: 1.5, note: "Wait for the pivot", added: "2026-11-02T10:00:00Z" },
    { ticker: B, close: 20, chg_pct: -1, rvol50: 0.8, note: "", added: "2026-11-05T10:00:00Z" },
  ],
  tv_list: `NASDAQ:${A}`,
};

const routes = () =>
  mockApi({
    "GET /api/watchlists/Mine": list,
    "GET /api/watchlists": { lists: ["Mine"], flags: [] },
    "POST /api/watchlists/Mine/remove": { ...list, rows: [list.rows[1]] },
    "POST /api/watchlists/Mine/add": { kind: "success", added: [A], already: [], unknown: [], lines: ["Added."] },
    "GET /api/scan-watchlists": { ep_watch: { label: "EP-Watch", rows: [{}, {}] }, bo_watch: { label: "BO-Watch", rows: [] } },
    "GET /api/alerts": { directions: ["above", "below"], alerts: [{ alert_id: "1", ticker: A, level: 9, direction: "above", note: "" }], fired: [] },
    "GET /api/chart-lists/hits": { id: "hits", label: "Today's hits", rows: [{ ticker: A, grade: "A+", setup: "EP 10:30", last: 10, chg_pct: 1, rvol: 1, signal_id: null }] },
    "GET /api/sparks": {},
    "GET /api/symbols": { asof: "x", symbols: [[A, "Wizard Holdings"]] },
  });

describe("Watchlists", () => {
  beforeEach(() => resetSymbols());

  it("groups the rail into my lists, the scans and alerts, with their counts", async () => {
    routes();
    render(<Watchlists params={new URLSearchParams()} />);
    const rail = await screen.findByRole("navigation", { name: "Lists" });
    expect(within(rail).getByText("My lists")).toBeInTheDocument();
    expect(await within(rail).findByRole("button", { name: /Mine\s*2/ })).toBeInTheDocument();
    expect(within(rail).getByRole("button", { name: /EP-Watch\s*2/ })).toBeInTheDocument();
    expect(within(rail).getByRole("button", { name: /Price alerts\s*1/ })).toBeInTheDocument();
    expect(within(rail).getByRole("button", { name: "+ New list" })).toBeInTheDocument();
  });

  it("shows the table with today's grade and removes the selected rows", async () => {
    const calls = routes();
    render(<Watchlists params={new URLSearchParams()} />);
    const table = await screen.findByRole("table", { name: "Watchlist Mine" });
    await waitFor(() => expect(within(table).getByText("EP 10:30")).toBeInTheDocument()); // the hit today
    expect(within(table).getByText("Wait for the pivot")).toBeInTheDocument();
    fireEvent.click(within(table).getByRole("checkbox", { name: `Select ${A}` }));
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open as Chart list" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove selected" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/Mine/remove") && JSON.stringify(c.body).includes(A))).toBe(true));
    await waitFor(() => expect(screen.queryByText("1 selected")).not.toBeInTheDocument());
  });

  it("adds typed tickers from the head of the list", async () => {
    const calls = routes();
    render(<Watchlists params={new URLSearchParams()} />);
    await screen.findByRole("table", { name: "Watchlist Mine" });
    fireEvent.change(screen.getByLabelText("Add tickers"), { target: { value: A } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/Mine/add"))).toBe(true));
  });
});
