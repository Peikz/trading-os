import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { BoardRow } from "../api";
import { type Call, mockApi } from "../test/mockApi";
import { pushTickers, screenName, titleLine, Today } from "./Today";

// Synthetic tickers, built from letters so no real symbol appears here.
const [A, B, C, D, E] = ["W", "X", "Y", "V", "K"].map((x) => [x, "Z", "Q", x].join(""));

vi.mock("../components/CandleChart", () => ({
  CandleChart: ({ bars, levels }: { bars: { ticker: string }; levels: Record<string, number> }) => (
    <div data-testid="chart">
      {bars.ticker} {Object.keys(levels).join(",")}
    </div>
  ),
}));

function row(ticker: string, grade: string, extra: Partial<BoardRow> = {}): BoardRow {
  return {
    ticker,
    scan: "ep_am",
    scan_label: "EP 10:30",
    grade,
    run_label: "2026-11-03 · Intraday 10:15",
    run_slot: "am",
    exchange: "NASDAQ",
    chg_pct: 2.1,
    facts: [],
    stats: [
      { label: "ADR", value: "5.0%" },
      { label: "Mkt cap", value: "$2.0B" },
    ],
    levels: { entry: 10, stop: 9 },
    decision: { text: "Buy at 10:30 New York", local: "16:30 in Copenhagen", session: "2026-11-04", day: "Wed 04 Nov" },
    why: {
      summary: "5 quality points",
      points: [
        { ok: true, text: "Earnings reaction day" },
        { ok: false, text: "Short interest over 10 %" },
      ],
      lines: ["640 past trades in 2016-26: 54% won, average +0.62R."],
    },
    ...extra,
  };
}

const ticket = {
  kinds: { market: "Market", limit: "Limit", stop: "Stop (buy-stop)" },
  default: "market",
  kind: "market",
  price_label: "Expected price (sizing)",
  plan_price: 10,
  note: null,
  error: null,
  ticket: {
    order_type: "market", shares: 1000, est_entry: 10, stop: 9, risk_usd: 1000,
    position_usd: 10000, capped: false, when: "~10:30 New York (16:30 CPH)",
    lines: [{ label: "Buy", value: "1000" }, { label: "Stop loss (own order, GTC)", value: "9.00" }],
    caption: "Risk 1,000 USD (1,000 USD) · position 10,000 USD · sized on 10.00",
    summary: "Buy 1000 · Market · Day · stop loss 9.00 GTC",
  },
};

const NEXT = { slot: "am", name: "10:15 check", when: "Wed 04 Nov, 10:10 New York (16:10 in Copenhagen)", at: "" };
const position = {
  ticker: D, setup: "EP-AH", direction: "long", shares: 400, entry_date: "2026-10-27", entry: 20,
  price: 22, move_pct: -0.6, open_r: 1.5, pnl: 800, to_stop_pct: 8, stop: 20.2, facts: ["Day 6 of 21: hold"],
};

let sent: Call[] = [];
function routes(graded: BoardRow[], extra: Record<string, unknown> = {}) {
  sent = mockApi({
    "GET /api/today?scope=graded": { scope: "graded", rows: graded, hidden_c: 3, total: graded.length + 3, next_scan: NEXT },
    "GET /api/today?scope=watchlists": { scope: "watchlists", rows: [row(C, "–", { scan: "watchlist", levels: {}, decision: null })], hidden_c: 0, total: 1 },
    "GET /api/today?scope=pushed": { scope: "pushed", rows: [...graded, row(E, "C", { scan: "vcp", scan_label: "VCP", decision: null })], hidden_c: 0, total: 3 },
    "GET /api/positions": { source: "close", totals: { positions: 1, open_pnl: 800, at_risk_usd: 0, at_risk_pct: 0 }, cards: [position] },
    "GET /api/bars/": (url: string) => ({ ticker: url.split("/")[3].split("?")[0], tf: "1D", candles: [], lines: [] }),
    "POST /api/ticket": (_: string, b: unknown) => ({ ...ticket, kind: (b as { kind: string | null }).kind ?? "market" }),
    "POST /api/ticket/place": { plan_id: "p1", message: "Saved as a plan. Your fill will match it in the Journal." },
    "POST /api/flags": (_: string, b: unknown) => ({ message: `${(b as { ticker: string }).ticker} → Flag green` }),
    "POST /api/watchlists/": { name: "Flag green", rows: [], columns: [], label: null, tv_list: "" },
    "GET /api/stock-notes/": [],
    "POST /api/stock-notes/": [{ note_id: "n1", note_date: "2026-11-03", text: "tight flag" }],
    "GET /api/alerts": { directions: ["above", "below"], alerts: [], fired: [] },
    ...extra,
  });
}
const urls = () => sent.map((c) => c.url);

describe("Today", () => {
  it("leads with the decision: the queue's three parts, the buy time and the plan's numbers", async () => {
    routes([row(B, "A+"), row(A, "A", { scan: "ma_surf", scan_label: "MA-surf" })]);
    render(<Today />);
    expect(await screen.findByText("2 setups to act on · 1 position · 1 on watch")).toBeInTheDocument();
    const queue = screen.getByRole("navigation", { name: "Queue" });
    expect(within(queue).getByText("To act on")).toBeInTheDocument();
    expect(within(queue).getByText("Your positions")).toBeInTheDocument();
    expect(within(queue).getByText("Watching")).toBeInTheDocument();
    const plan = await screen.findByLabelText(`${B} plan`);
    expect(within(plan).getByText("Buy at 10:30 New York")).toBeInTheDocument();
    expect(within(plan).getByText("16:30 in Copenhagen · Wed 04 Nov")).toBeInTheDocument();
    expect(await within(plan).findByText("1,000")).toBeInTheDocument(); // shares, from the ticket
    expect(within(plan).getByText("$1,000")).toBeInTheDocument(); // risk
    expect(within(plan).getByText("Buy 1000 · Market · Day · stop loss 9.00 GTC")).toBeInTheDocument();
    const why = screen.getByLabelText("Why A+");
    expect(why).toHaveTextContent("5 quality points");
    expect(why).toHaveTextContent("Earnings reaction day");
    expect(screen.getByLabelText("Key facts")).toHaveTextContent("Market cap$2.0B");
    expect(screen.getByLabelText("Key facts")).toHaveTextContent("Daily range5.0%");
    expect(await screen.findByTestId("chart")).toHaveTextContent(`${B} entry,stop`);
  });

  it("copies the order, edits its type and saves 'I placed it in Saxo' as a plan", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    routes([row(B, "A+")]);
    render(<Today />);
    const plan = await screen.findByLabelText(`${B} plan`);
    await within(plan).findByText("Buy 1000 · Market · Day · stop loss 9.00 GTC");
    fireEvent.click(within(plan).getByText("Copy order for Saxo"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${B}: Buy 1000 · Market · Day · stop loss 9.00 GTC`));
    fireEvent.click(within(plan).getByText("Edit order"));
    fireEvent.change(await within(plan).findByLabelText("Order type"), { target: { value: "stop" } });
    await waitFor(() =>
      expect(sent.some((c) => c.url === "/api/ticket" && (c.body as { kind: string }).kind === "stop")).toBe(true),
    );
    expect(within(plan).getByLabelText("Copy Buy")).toBeInTheDocument();
    fireEvent.click(within(plan).getByText("I placed it in Saxo"));
    expect(await within(plan).findByText(/Saved as a plan/)).toBeInTheDocument();
    const place = sent.find((c) => c.url === "/api/ticket/place")!;
    expect((place.body as { row: BoardRow; kind: string }).row.ticker).toBe(B);
    expect((place.body as { kind: string }).kind).toBe("stop");
  });

  it("flips the queue with the arrow keys, watches with W and writes a note with N", async () => {
    routes([row(B, "A+"), row(A, "A")]);
    render(<Today />);
    await screen.findByLabelText(`${B} plan`);
    fireEvent.keyDown(window, { key: "ArrowDown" });
    expect(await screen.findByLabelText(`${A} plan`)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowDown" }); // the position
    expect(await screen.findByLabelText(`${D} position`)).toHaveTextContent("+1.50R");
    fireEvent.keyDown(window, { key: "ArrowDown" }); // the watched stock
    expect(await screen.findByLabelText(`${C} watch`)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowDown" }); // round to the top
    expect(await screen.findByLabelText(`${B} plan`)).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "w" });
    await waitFor(() => expect(sent.find((c) => c.url === "/api/flags")?.body).toEqual({ ticker: B, name: "Flag green" }));
    expect(await screen.findByRole("status")).toHaveTextContent(`${B} is on your watchlist`);

    fireEvent.keyDown(window, { key: "n" });
    await waitFor(() => expect(screen.getByLabelText("Note")).toHaveFocus());
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "tight flag" } });
    fireEvent.click(screen.getByText("Add note"));
    await waitFor(() => expect(sent.some((c) => c.method === "POST" && c.url === `/api/stock-notes/${B}`)).toBe(true));
  });

  it("takes a watched stock off the watchlist with the star", async () => {
    routes([row(B, "A+")]);
    render(<Today />);
    fireEvent.click(await screen.findByText(C));
    const star = await screen.findByRole("button", { name: /Watching: remove/ });
    fireEvent.click(star);
    await waitFor(() =>
      expect(sent.find((c) => c.url === "/api/watchlists/Flag%20green/remove")?.body).toEqual({ tickers: [C] }),
    );
  });

  it("asks for MA 10/20/50 by default and steps 1D/1W/1M from the bar switch", async () => {
    routes([row(B, "A+")]);
    render(<Today />);
    await screen.findByLabelText(`${B} plan`);
    await waitFor(() => expect(urls().some((u) => u.startsWith(`/api/bars/${B}`))).toBe(true));
    const bars = urls().find((u) => u.startsWith(`/api/bars/${B}`))!;
    expect(new URLSearchParams(bars.split("?")[1]).get("indicators")).toBe("MA 10,MA 20,MA 50");
    fireEvent.click(screen.getByRole("button", { name: "1W" }));
    await waitFor(() => expect(urls().some((u) => u.includes("tf=1W"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: /Indicators/ }));
    fireEvent.click(screen.getByLabelText("MA 200"));
    await waitFor(() => expect(urls().some((u) => u.includes("MA%20200") || u.includes("MA+200"))).toBe(true));
  });

  it("is calm on a quiet day: nothing to buy, the next scan, and the way to the C setups", async () => {
    routes([]);
    render(<Today />);
    expect(await screen.findByText("Nothing to buy today")).toBeInTheDocument();
    expect(screen.getByText("Nothing to act on · 1 position · 1 on watch")).toBeInTheDocument();
    expect(screen.getByText(/Next scan: the 10:15 check, Wed 04 Nov, 10:10 New York/)).toBeInTheDocument();
    expect(screen.getByText("Every scan hit").closest("a")).toHaveAttribute("href", "#/stocks?src=scans");
    fireEvent.click(screen.getByRole("button", { name: "See the 3 C setups" }));
    await waitFor(() => expect(urls()).toContain("/api/today?scope=pushed"));
    expect(await screen.findByText("C setups · no tested edge")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Look at the C setups" }));
    const plan = await screen.findByLabelText(`${E} plan`);
    expect(plan).toHaveTextContent("Not a buy by the study");
  });

  it("puts a push link's stocks first", async () => {
    window.history.replaceState(null, "", `/?push=am&t=${E}`);
    routes([row(B, "A+")], {
      "GET /api/today?scope=all": { scope: "all", rows: [row(E, "A", { scan: "ep_day" })], hidden_c: 0, total: 1 },
    });
    render(<Today />);
    expect(await screen.findByText("From the push")).toBeInTheDocument();
    expect(await screen.findByLabelText(`${E} plan`)).toBeInTheDocument();
    expect(urls()).toContain(`/api/today?scope=all&t=${E}`);
    window.history.replaceState(null, "", "/");
  });

  it("shows one card per stock on a phone, flipped with next and the dots", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("639"),
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    routes([row(B, "A+"), row(A, "A")]);
    render(<Today />);
    const card = await screen.findByLabelText(`${B} card`);
    expect(within(card).getByText("Buy at 10:30 New York")).toBeInTheDocument();
    expect(await within(card).findByText("Copy order for Saxo")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Stock 1 of 4" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next stock" }));
    expect(await screen.findByLabelText(`${A} card`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: D }));
    expect(await screen.findByLabelText(`${D} card`)).toHaveTextContent("+1.50R");
    vi.unstubAllGlobals();
  });
});

describe("Today's helpers", () => {
  it("writes the title line", () => {
    expect(titleLine(2, 1, 2)).toBe("2 setups to act on · 1 position · 2 on watch");
    expect(titleLine(1, 0, 0)).toBe("1 setup to act on · 0 positions · 0 on watch");
    expect(titleLine(0, 2, 1)).toBe("Nothing to act on · 2 positions · 1 on watch");
  });

  it("reads a push link's stocks and a screen's name", () => {
    expect(pushTickers(`?push=ah&t=${A},${B}`)).toEqual([A, B]);
    expect(pushTickers("")).toEqual([]);
    expect(screenName(`?screen=Mine&t=${A}`)).toBe("Mine");
    expect(screenName(`?t=${A}`)).toBeNull();
  });
});
