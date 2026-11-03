import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { Journal } from "./Journal";

const A = ["W", "Z", "Q", "W"].join(""); // synthetic

vi.mock("../components/RCurve", () => ({
  RCurve: ({ points }: { points: unknown[] }) => <div data-testid="curve">{points.length}</div>,
}));

const totals = { positions: 1, open_pnl: 810, at_risk_usd: 910, at_risk_pct: 0.9 };
const plans = {
  today: "2026-11-03",
  plans: [{ status: "open", ticker: A, entry: 10, stop: 9, shares: 500, plan_id: "p1" }],
  hits: [{ ticker: A, scan: "ep_day", plan_entry: 10, plan_stop: 9, label: `${A} · ep_day · buy 10.00 stop 9.00` }],
  setups: ["ep_day", "vcp"],
};

function routes() {
  return mockApi({
    "GET /api/journal/open": {
      totals,
      rows: [{ ticker: A, open_pnl: 810, open_r: 8.1 }],
      plan: [{ ticker: A, rule: "hold", held: 3, hold: 21 }],
      plan_day: "2026-10-30",
      plan_caption: "hold: sell at the close after `hold` sessions",
    },
    "GET /api/journal/setups": ["ep_day", "vcp"],
    "POST /api/journal/fills": { message: `Saved: buy 100 ${A} @ 10.` },
    "GET /api/journal/plans/suggest": {
      suggestion: { shares: 500, position_usd: 5000, risk_usd: 500, capped: false },
      text: "Suggested: 500 shares · $5,000 · risk $500",
    },
    "GET /api/journal/plans": plans,
    "POST /api/journal/plans/p1/cancel": { ...plans, plans: [{ ...plans.plans[0], status: "cancelled" }] },
    "POST /api/journal/plans": { ...plans, message: "Plan saved." },
    "GET /api/journal/closed": {
      stats: { trades: 1, win_rate: 100, avg_r: 2, pnl: 100 },
      curve: [{ time: "2026-06-10", value: 2 }],
      trades: [{ trade_id: "t1", ticker: A, pnl: 100, r_multiple: 2, mfe_r: 3, mae_r: -0.5, label: `${A} 2026-06-01 → 2026-06-10 (100)` }],
      caption: "MFE/MAE: best and worst price",
    },
    "GET /api/grades/trade/t1": { kind: "trade", ref_id: "t1", grades: ["", "A", "B", "C"], grade: "", notes: "", tags: "", attachments: [] },
    "GET /api/journal/real-vs-study": { columns: ["setup", "your_trades"], rows: [{ setup: "ep_day", your_trades: 1 }], caption: "Study = ..." },
  });
}

describe("Journal", () => {
  it("shows open positions and what each plan says", async () => {
    routes();
    render(<Journal />);
    expect(await screen.findByLabelText("Open positions")).toHaveTextContent("$810");
    expect(screen.getByText("$910 · 0.9%")).toBeInTheDocument();
    expect(screen.getByLabelText("What each plan says")).toHaveTextContent("hold");
  });

  it("logs a fill", async () => {
    const calls = routes();
    render(<Journal tab="trades" />);
    fireEvent.change(await screen.findByLabelText("Ticker"), { target: { value: A.toLowerCase() } });
    fireEvent.change(screen.getByLabelText("Shares"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("Price"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Initial stop (entries)"), { target: { value: "9.5" } });
    fireEvent.click(screen.getByText("Save fill"));
    expect(await screen.findByText(`Saved: buy 100 ${A} @ 10.`)).toBeInTheDocument();
    const fill = calls.find((c) => c.url === "/api/journal/fills")!.body as Record<string, unknown>;
    expect(fill).toMatchObject({ ticker: A, side: "buy", shares: 100, price: 10, stop: 9.5 });
  });

  it("starts a plan from a scan hit with the suggested shares, and cancels one", async () => {
    const calls = routes();
    render(<Journal tab="plans" />);
    fireEvent.change(await screen.findByLabelText("Start from a scan hit"), {
      target: { value: plans.hits[0].label },
    });
    expect(screen.getByLabelText("Plan ticker")).toHaveValue(A);
    expect(await screen.findByText("Suggested: 500 shares · $5,000 · risk $500")).toBeInTheDocument();
    expect(screen.getByLabelText("Shares (suggested from your risk per trade)")).toHaveValue(500);
    fireEvent.click(screen.getByText("Save plan"));
    expect(await screen.findByText("Plan saved.")).toBeInTheDocument();
    const body = calls.find((c) => c.method === "POST" && c.url === "/api/journal/plans")!.body;
    expect(body).toMatchObject({ ticker: A, entry: 10, stop: 9, shares: 500, setup: "ep_day" });
    fireEvent.change(screen.getByLabelText("Cancel an open plan"), { target: { value: "p1" } });
    fireEvent.click(screen.getByText("Cancel plan"));
    await waitFor(() => expect(screen.getByLabelText("Plans")).toHaveTextContent("cancelled"));
  });

  it("shows closed trades with stats, the R curve and the grading form", async () => {
    routes();
    const { rerender } = render(<Journal tab="trades" />);
    expect(await screen.findByLabelText("Closed trades")).toHaveTextContent("-0.50");
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByTestId("curve")).toHaveTextContent("1");
    expect(await screen.findByLabelText("Grading form")).toHaveTextContent(`${A} trade`);
    rerender(<Journal tab="live" />);
    expect(await screen.findByLabelText("Real vs study")).toHaveTextContent("ep_day");
  });
});
