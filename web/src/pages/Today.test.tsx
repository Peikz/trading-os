import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { BoardRow, Today as TodayData } from "../api";
import { type Call, mockApi } from "../test/mockApi";
import { pushTickers, screenName, Today } from "./Today";

// Synthetic tickers, built from letters so no real symbol appears here.
const [A, B] = ["W", "X"].map((x) => [x, "Z", "Q", x].join(""));

function row(ticker: string, grade: string): BoardRow {
  return {
    ticker,
    scan: "ep_ah",
    scan_label: "EP-AH",
    grade,
    run_label: "2026-10-30 · eod",
    run_slot: "eod",
    exchange: "NASDAQ",
    facts: [`Buy 10.00 · 🛑 9.00 (day low)`, `100 sh · $1.0k · risk $100`],
    stats: [{ label: "ADR", value: "5.0%" }],
    levels: { entry: 10, stop: 9 },
  };
}

const today: TodayData = { scope: "graded", rows: [row(B, "A+"), row(A, "A")], hidden_c: 1, total: 3 };

vi.mock("../components/CandleChart", () => ({
  CandleChart: ({ title }: { title: string }) => <div data-testid="chart">{title}</div>,
}));

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
  },
};

let sent: Call[] = [];
beforeEach(() => {
  sent = mockApi({
    "GET /api/today": today,
    "GET /api/market": { tiles: [{ label: "QQQ light", value: "🟢 GREEN", delta: null }], details: [] },
    "GET /api/bars/": (url: string) => ({
      ticker: url.split("/")[3].split("?")[0], tf: "1D", candles: [], lines: [],
    }),
    "POST /api/ticket": ticket,
    "POST /api/ticket/place": { plan_id: "p1", message: "Saved as a plan. Your fill will match it in the Journal." },
    "POST /api/flags": (_: string, b: unknown) => ({ message: `${(b as { ticker: string }).ticker} → Flag green` }),
    "GET /api/stock-notes/": [],
    "GET /api/alerts": { directions: ["above", "below"], alerts: [], fired: [] },
    "POST /api/alerts": { directions: ["above", "below"], alerts: [], fired: [] },
  });
});
const urls = () => sent.map((c) => c.url);

describe("Today", () => {
  it("shows the queue, flips with the arrow keys and toggles 1D/1W with W", async () => {
    render(<Today />);
    expect(await screen.findByText("1 of 2 · 1 C hidden")).toBeInTheDocument();
    expect(screen.getByText("🟢 GREEN")).toBeInTheDocument();
    expect(screen.getByLabelText(`${B} card`)).toHaveTextContent("100 sh");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(await screen.findByLabelText(`${A} card`)).toBeInTheDocument();
    expect(screen.getByText("2 of 2 · 1 C hidden")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowRight" }); // wraps round
    expect(await screen.findByLabelText(`${B} card`)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "w" });
    await waitFor(() => expect(urls().some((u) => u.includes("tf=1W"))).toBe(true));
  });

  it("asks for MA 10/20/50 by default", async () => {
    render(<Today />);
    await screen.findByText("1 of 2 · 1 C hidden");
    await waitFor(() => expect(urls().some((u) => u.startsWith(`/api/bars/${B}`))).toBe(true));
    const bars = urls().find((u) => u.startsWith(`/api/bars/${B}`))!;
    expect(new URLSearchParams(bars.split("?")[1]).get("indicators")).toBe("MA 10,MA 20,MA 50");
  });

  it("jumps from the list", async () => {
    render(<Today />);
    await screen.findByText("1 of 2 · 1 C hidden");
    fireEvent.click(screen.getByRole("tab", { name: "List (2)" }));
    fireEvent.click(screen.getByText(`A · ${A} · EP-AH`));
    expect(await screen.findByLabelText(`${A} card`)).toBeInTheDocument();
  });
});

describe("Today, phase 2a", () => {
  it("shows the Saxo ticket with copy buttons and saves Placed as a plan", async () => {
    render(<Today />);
    expect(await screen.findByLabelText("Saxo ticket")).toBeInTheDocument();
    expect(await screen.findByText("1000")).toBeInTheDocument();
    expect(screen.getByLabelText("Copy Buy")).toBeInTheDocument();
    expect(screen.getByText("Market (plan)")).toBeInTheDocument();
    fireEvent.click(screen.getByText("✅ Placed in Saxo: save as plan"));
    expect(await screen.findByText(/Saved as a plan/)).toBeInTheDocument();
    const place = sent.find((c) => c.url === "/api/ticket/place")!;
    expect((place.body as { row: BoardRow }).row.ticker).toBe(B);
  });

  it("switches the order type and recomputes", async () => {
    render(<Today />);
    fireEvent.change(await screen.findByLabelText("Order type"), { target: { value: "stop" } });
    await waitFor(() =>
      expect(sent.some((c) => c.url === "/api/ticket" && (c.body as { kind: string }).kind === "stop")).toBe(true),
    );
  });

  it("F flags green, N opens the note, T hides the ticket", async () => {
    render(<Today />);
    await screen.findByText("1 of 2 · 1 C hidden");
    fireEvent.keyDown(window, { key: "f" });
    expect(await screen.findByRole("status")).toHaveTextContent(`${B} → Flag green`);
    const flag = sent.find((c) => c.url === "/api/flags")!;
    expect(flag.body).toEqual({ ticker: B, name: "Flag green" });
    fireEvent.keyDown(window, { key: "t" });
    expect(await screen.findByText("Ticket hidden (T shows it).")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "n" });
    await waitFor(() => expect(screen.getByLabelText("Note")).toHaveFocus());
    expect(screen.getByLabelText("Alert price")).toHaveValue(0);
  });

  it("grid shows four at once and list shows every card", async () => {
    render(<Today />);
    await screen.findByText("1 of 2 · 1 C hidden");
    fireEvent.click(screen.getByText("Grid"));
    expect(await screen.findByText("1-2 of 2 · 1 C hidden")).toBeInTheDocument();
    expect(screen.getAllByTestId("chart")).toHaveLength(2);
    fireEvent.click(screen.getByText("List"));
    expect(await screen.findByLabelText(`${A} card`)).toBeInTheDocument();
    expect(screen.getByLabelText(`${B} card`)).toBeInTheDocument();
  });

  it("asks for your watchlists in the My watchlists scope", async () => {
    render(<Today />);
    await screen.findByText("1 of 2 · 1 C hidden");
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "watchlists" } });
    await waitFor(() => expect(urls()).toContain("/api/today?scope=watchlists"));
  });
});

describe("screenName", () => {
  it("reads the screen a flip link came from", () => {
    expect(screenName(`?screen=Mine&t=${A}`)).toBe("Mine");
    expect(screenName(`?t=${A}`)).toBeNull();
  });
});

describe("pushTickers", () => {
  it("reads a push link's stocks", () => {
    expect(pushTickers(`?push=ah&t=${A},${B}`)).toEqual([A, B]);
    expect(pushTickers("")).toEqual([]);
  });
});
