// Round 4 on Today: the view (Focus, Grid, List), "Show" (scopes and your watchlists), the run
// picker that reaches earlier days, "All scans", the keys F / T / W, and the phone card's order
// edit, why, note and alert. Synthetic tickers, built from letters.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { BoardRow } from "../api";
import { pickRun } from "../shell/todayRun";
import { type Call, mockApi } from "../test/mockApi";
import { Today } from "./Today";

const [A, B, C, D, E] = ["W", "X", "Y", "V", "K"].map((x) => [x, "Z", "Q", x].join(""));

vi.mock("../components/CandleChart", () => ({
  CandleChart: ({ bars }: { bars: { ticker: string } }) => <div data-testid="chart">{bars.ticker}</div>,
}));

function row(ticker: string, grade: string, extra: Partial<BoardRow> = {}): BoardRow {
  return {
    ticker,
    scan: "ep_am",
    scan_label: "EP 10:30",
    grade,
    run_label: "2026-11-03 · Intraday 10:15",
    run_slot: "am",
    chg_pct: 2.1,
    facts: [],
    stats: [{ label: "ADR", value: "5.0%" }],
    levels: { entry: 10, stop: 9 },
    decision: { text: "Buy at 10:30 New York", local: "16:30 in Copenhagen", session: "2026-11-04", day: "Wed 04 Nov" },
    why: { summary: "5 quality points", points: [{ ok: true, text: "Earnings reaction day" }], lines: [] },
    ...extra,
  };
}

const ticket = {
  kinds: { market: "Market", limit: "Limit" },
  default: "market",
  kind: "market",
  price_label: "Expected price (sizing)",
  plan_price: 10,
  note: null,
  error: null,
  ticket: {
    order_type: "market", shares: 1000, est_entry: 10, stop: 9, risk_usd: 1000, position_usd: 10000, capped: false,
    when: "~10:30", lines: [{ label: "Buy", value: "1000" }, { label: "Stop loss (own order, GTC)", value: "9.00" }],
    caption: "Risk 1,000 USD", summary: "Buy 1000 · Market · Day · stop loss 9.00 GTC",
  },
};

let sent: Call[] = [];
const urls = () => sent.map((c) => c.url);
function routes(extra: Record<string, unknown> = {}) {
  sent = mockApi({
    "GET /api/today?scope=graded": { scope: "graded", rows: [row(A, "A+"), row(B, "A"), row(C, "B"), row(D, "B"), row(E, "A")], hidden_c: 1, total: 6, next_scan: null },
    "GET /api/today?scope=pushed": { scope: "pushed", rows: [row(A, "A+"), row(B, "C", { decision: null })], hidden_c: 0, total: 2 },
    "GET /api/today?scope=all": { scope: "all", rows: [row(A, "A+")], hidden_c: 0, total: 1 },
    "GET /api/today?scope=watchlists": { scope: "watchlists", rows: [row(B, "", { scan: "watchlist", levels: {}, decision: null })], hidden_c: 0, total: 1 },
    "GET /api/watchlists": { lists: ["Flag green", "Leaders"], flags: [] },
    "GET /api/positions": { source: "close", totals: { positions: 0, open_pnl: 0, at_risk_usd: 0, at_risk_pct: 0 }, cards: [] },
    "GET /api/bars/": (url: string) => ({ ticker: url.split("/")[3].split("?")[0], tf: "1D", candles: [], lines: [] }),
    "POST /api/ticket": ticket,
    "POST /api/ticket/place": { plan_id: "p1", message: "Saved as a plan." },
    "POST /api/flags": { message: "ok" },
    "POST /api/watchlists/": { name: "Flag green", rows: [], columns: [], label: null, tv_list: "" },
    "GET /api/stock-notes/": [],
    "GET /api/alerts": { directions: ["above", "below"], alerts: [], fired: [] },
    "GET /api/journal/daily-notes/today": { day: "2026-11-19", text: "", note_id: null },
    "GET /api/today-runs": {
      session: "2026-11-19",
      all: { id: "all", label: "All today", count: 2 },
      runs: [{ id: "2026-11-19_am", slot: "am", name: "10:15", ny: "10:17", cph: "16:17", count: 2 }],
    },
    "GET /api/runs": [
      { id: "2026-11-19_am", label: "2026-11-19 · am", session: "2026-11-19", slot: "am", kind: "scheduled" },
      { id: "2026-11-18_eod", label: "2026-11-18 · eod", session: "2026-11-18", slot: "eod", kind: "scheduled" },
    ],
    ...extra,
  });
}

beforeEach(() => {
  pickRun("all");
  window.localStorage.clear();
  window.location.hash = "";
  window.history.replaceState(null, "", "/");
});

describe("Today's view", () => {
  it("shows four charts at a time in the Grid and pages through them", async () => {
    routes();
    render(<Today />);
    await screen.findByLabelText(`${A} plan`);
    fireEvent.click(screen.getByRole("button", { name: "Grid" }));
    const grid = await screen.findByRole("region", { name: "Grid of charts" });
    expect(within(grid).getAllByRole("article")).toHaveLength(4);
    expect(within(grid).getByText("1-4 of 6")).toBeInTheDocument();
    fireEvent.click(within(grid).getByRole("button", { name: "Next four" }));
    expect(await within(grid).findByText("5-6 of 6")).toBeInTheDocument();
    expect(within(grid).getAllByRole("article")).toHaveLength(2);
    expect(urls().filter((u) => u.startsWith("/api/bars/"))).not.toHaveLength(0);
  });

  it("shows one card per stock in the List, with its plan and why", async () => {
    routes();
    render(<Today />);
    await screen.findByLabelText(`${A} plan`);
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    const list = await screen.findByRole("region", { name: "List of cards" });
    expect(within(list).getByText("6 signals")).toBeInTheDocument();
    const card = within(list).getByRole("article", { name: `${A} card` });
    expect(within(card).getByText("Buy at 10:30 New York")).toBeInTheDocument();
    expect(within(card).getByLabelText("Why A+")).toHaveTextContent("5 quality points");
  });

  it("reads another list with Show: the pushed scans with the C setups, and your watchlists", async () => {
    routes();
    render(<Today />);
    await screen.findByLabelText(`${A} plan`);
    fireEvent.click(screen.getByRole("button", { name: /Show.*Today's list/ }));
    fireEvent.click(screen.getByRole("option", { name: "Pushed, incl. C" }));
    expect(await screen.findByText("2 stocks · Pushed, incl. C")).toBeInTheDocument();
    expect(urls().some((u) => u.startsWith("/api/today?scope=pushed"))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /Show.*Pushed/ }));
    fireEvent.click(screen.getByRole("option", { name: "Leaders" }));
    expect(await screen.findByText("1 stock · Leaders")).toBeInTheDocument();
    expect(urls().some((u) => u.includes("scope=watchlists") && u.includes("wl=Leaders"))).toBe(true);
    // the run picker is for scans; a watchlist has none
    expect(screen.queryByRole("group", { name: "Scan run" })).not.toBeInTheDocument();
  });

  it("reaches an earlier day's run from the picker", async () => {
    routes({
      "GET /api/today?scope=graded&run=2026-11-18_eod": { scope: "graded", rows: [row(D, "A")], hidden_c: 0, total: 1, next_scan: null },
    });
    render(<Today />);
    const picker = await screen.findByRole("group", { name: "Scan run" });
    fireEvent.click(await within(picker).findByRole("button", { name: /Earlier/ }));
    fireEvent.click(screen.getByRole("option", { name: "2026-11-18 · eod" }));
    await waitFor(() => expect(urls().some((u) => u.includes("run=2026-11-18_eod"))).toBe(true));
    expect(await screen.findByLabelText(`${D} plan`)).toBeInTheDocument();
    expect(within(picker).getByRole("button", { name: /Earlier run/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("flips through a screen's stocks from a hash link, and says where they came from", async () => {
    window.location.hash = `#/today?screen=Mine&t=${E},${D}`;
    routes({
      "GET /api/today?scope=all&t=": { scope: "screen", rows: [row(E, "", { scan: "screen" }), row(D, "", { scan: "screen" })], hidden_c: 0, total: 2 },
    });
    render(<Today />);
    expect(await screen.findByText("From the screen: Mine")).toBeInTheDocument();
    expect(urls().some((u) => u.startsWith("/api/today?scope=all") && u.includes("screen=Mine") && u.includes(`t=${E}%2C${D}`))).toBe(true);
    expect(await screen.findByLabelText(`${E} screen`)).toHaveTextContent("A screen is a list to look at");
  });
});

describe("Today's keys", () => {
  it("watches with F, steps the bars with W and opens the Saxo values with T", async () => {
    routes();
    render(<Today />);
    await screen.findByLabelText(`${A} plan`);
    fireEvent.keyDown(window, { key: "f" });
    await waitFor(() => expect(sent.find((c) => c.url === "/api/flags")?.body).toEqual({ ticker: A, name: "Flag green" }));
    fireEvent.keyDown(window, { key: "w" });
    await waitFor(() => expect(urls().some((u) => u.includes("tf=1W"))).toBe(true));
    fireEvent.keyDown(window, { key: "w" });
    await waitFor(() => expect(urls().some((u) => u.includes("tf=1M"))).toBe(true));
    expect(screen.queryByLabelText("Edit order")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "t" });
    const edit = await screen.findByLabelText("Edit order");
    expect(await within(edit).findByLabelText("Copy Buy")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "t" });
    await waitFor(() => expect(screen.queryByLabelText("Edit order")).not.toBeInTheDocument());
  });
});

describe("All scans", () => {
  const table = {
    run: "2026-11-19_am",
    label: "2026-11-19 · am",
    scans: [
      {
        scan: "ep_am",
        label: "EP 10:30",
        shown: 2,
        total: 3,
        columns: [
          { header: "Ticker", key: "ticker", fmt: "text" },
          { header: "Study grade", key: "grade", fmt: "text" },
          { header: "Gap %", key: "gap_pct", fmt: "signed1" },
          { header: "Chart", key: "tradingview", fmt: "link" },
        ],
        rows: [
          { ticker: A, grade: "A+", gap_pct: 12.34, tradingview: "https://example.test/a" },
          { ticker: B, grade: "A", gap_pct: 8, tradingview: "https://example.test/b" },
        ],
        blocks: [{ ticker: A, title: "🅰 Study A+ · +0.52R", lines: ["Buy 10.00 · 🛑 9.00 (day low)"] }],
        facts: ["- **" + A + "** · gap 12%"],
        charts: [A],
      },
    ],
  };

  it("is closed until opened, then shows each pushed scan's table, blocks, facts and chart images", async () => {
    routes({ "GET /api/scan-tables": table });
    render(<Today />);
    await screen.findByLabelText(`${A} plan`);
    expect(urls().some((u) => u.startsWith("/api/scan-tables"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /all scans/i }));
    const t = await screen.findByRole("region", { name: "EP 10:30 table" });
    expect(urls()).toContain("/api/scan-tables?run=2026-11-19_am"); // today's newest run
    expect(within(t).getByText(/2 of 3 hits/)).toBeInTheDocument();
    expect(within(t).getByRole("columnheader", { name: "Gap %" })).toBeInTheDocument();
    expect(within(t).getByText("+12.3")).toBeInTheDocument();
    expect(within(t).getAllByRole("link", { name: "TradingView ↗" })).toHaveLength(2);
    expect(within(t).getByLabelText(/A\+, A and B hits as the push shows them/)).toHaveTextContent("Study A+ · +0.52R");
    expect(within(t).getByAltText(`${A} chart`)).toHaveAttribute("src", `/api/run-chart/2026-11-19_am/ep_am/${A}`);
    // a click on a header sorts, and the CSV is one click
    fireEvent.click(within(t).getByRole("button", { name: "Gap %" }));
    const rows = within(within(t).getByRole("table", { name: "EP 10:30 hits" })).getAllByRole("row");
    expect(rows[1]).toHaveTextContent(B); // low to high first
    expect(within(t).getByRole("button", { name: "Download EP 10:30 hits as CSV" })).toBeInTheDocument();
  });
});

describe("The phone card, behind Why and facts", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("640"), addEventListener: () => {}, removeEventListener: () => {} }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("edits the order, copies each value, and has the why card, a note and a price alert", async () => {
    routes();
    render(<Today />);
    const card = await screen.findByLabelText(`${A} plan`);
    expect(await within(card).findByText("Copy order for Saxo")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Why and facts" }));
    fireEvent.click(within(card).getByRole("button", { name: "Edit order" }));
    const edit = await within(card).findByLabelText("Edit order");
    expect(within(edit).getByLabelText("Order type")).toBeInTheDocument();
    expect(within(edit).getByLabelText("Expected price (sizing)")).toBeInTheDocument();
    expect(within(edit).getByLabelText("Copy Stop loss (own order, GTC)")).toBeInTheDocument();
    fireEvent.change(within(edit).getByLabelText("Expected price (sizing)"), { target: { value: "10.5" } });
    await waitFor(() => expect(sent.some((c) => c.url === "/api/ticket" && (c.body as { price: number }).price === 10.5)).toBe(true));
    expect(within(card).getByLabelText("Why A+")).toHaveTextContent("Earnings reaction day");
    expect(within(card).getByLabelText("Note")).toBeInTheDocument();
    expect(within(card).getByLabelText("Alert price")).toBeInTheDocument();
    // the bars and indicator controls sit above the chart
    expect(within(card).getByRole("button", { name: "1W" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: /Indicators/ })).toBeInTheDocument();
  });
});
