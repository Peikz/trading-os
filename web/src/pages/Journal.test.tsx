import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { Journal } from "./Journal";

const A = ["W", "Z", "Q", "W"].join(""); // synthetic

vi.mock("../components/DrawChart", () => ({
  DrawChart: ({ data }: { data: { candles: unknown[]; markers: unknown[] } }) => (
    <div data-testid="trade-chart">
      {data.candles.length} bars, {data.markers.length} fills
    </div>
  ),
}));
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
      by_conviction: [{ conviction: 2, trades: 1, win_pct: 100, mean_r: 2, total_r: 2 }],
      curve: [{ time: "2026-06-10", value: 2 }],
      trades: [
        {
          trade_id: "t1", ticker: A, direction: "long", setup: "ep_day", entry_date: "2026-06-01", exit_date: "2026-06-10",
          pnl: 100, r_multiple: 2, mfe_r: 3, mae_r: -0.5, grade: "A", conviction: 2,
          label: `${A} 2026-06-01 → 2026-06-10 (100)`,
        },
      ],
      caption: "MFE/MAE: best and worst price",
    },
    "GET /api/chart/": {
      candles: [
        { time: "2026-05-29", open: 9, high: 10, low: 8, close: 9.5, volume: 1 },
        { time: "2026-06-01", open: 10, high: 11, low: 9, close: 10.5, volume: 1 },
      ],
      lines: [], avwaps: [], trend: [], markers: [{ time: "2026-06-01" }], levels: [], visible: null,
    },
    "GET /api/grades/trade/t1": {
      kind: "trade", ref_id: "t1", grades: ["", "A", "B", "C"], grade: "A", notes: "clean", tags: "",
      conviction: 2, convictions: [1, 2, 3], attachments: [],
    },
    "PUT /api/grades/trade/t1": (_u: string, body: unknown) => ({
      kind: "trade", ref_id: "t1", grades: ["", "A", "B", "C"], grade: "A", notes: "clean", tags: "",
      convictions: [1, 2, 3], attachments: [], message: "Saved.", ...(body as object),
    }),
    "GET /api/journal/daily-notes/today": { day: "2026-11-18", text: "Quiet", note_id: "n1" },
    "PUT /api/journal/daily-notes/today": (_u: string, body: unknown) => ({ day: "2026-11-18", note_id: "n1", ...(body as object) }),
    "GET /api/journal/real-vs-study": { columns: ["setup", "your_trades"], rows: [{ setup: "ep_day", your_trades: 1 }], caption: "Study = ..." },
  });
}

describe("Journal", () => {
  it("shows open positions and what each plan says", async () => {
    routes();
    render(<Journal tab="positions" />);
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

  it("changes a trade's conviction through the grading form", async () => {
    const calls = routes();
    render(<Journal tab="trades" />);
    await screen.findByLabelText("Grading form");
    const group = screen.getByRole("radiogroup", { name: "Conviction" });
    expect(group.querySelectorAll("input")).toHaveLength(4); // none, 1, 2, 3
    await waitFor(() => expect(screen.getByRole("radio", { name: "2" })).toBeChecked());
    fireEvent.click(screen.getByRole("radio", { name: "3" }));
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.url === "/api/grades/trade/t1")).toBe(true));
    const body = calls.find((c) => c.method === "PUT" && c.url === "/api/grades/trade/t1")!.body;
    expect(body).toMatchObject({ grade: "A", conviction: 3, notes: "clean" });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });

  it("saves today's note from the collapsible card", async () => {
    const calls = routes();
    render(<Journal tab="trades" />);
    fireEvent.click(await screen.findByRole("button", { name: /Today's note/ }));
    const box = await screen.findByLabelText("Today's note text");
    await waitFor(() => expect(box).toHaveValue("Quiet"));
    fireEvent.change(box, { target: { value: "Quiet, then a gap up" } });
    fireEvent.click(screen.getByRole("button", { name: "Save today's note" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const sent = calls.find((c) => c.method === "PUT" && c.url === "/api/journal/daily-notes/today")!;
    expect(sent.body).toEqual({ text: "Quiet, then a gap up" });
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

  it("shows closed trades with stats and the R curve, and the first trade beside them", async () => {
    routes();
    const { rerender } = render(<Journal tab="trades" />);
    const table = await screen.findByLabelText("Closed trades");
    expect(table).toHaveTextContent("+2.00R");
    expect(table).toHaveTextContent("◆2"); // the conviction column
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByTestId("curve")).toHaveTextContent("1");
    // The detail pane: the chart with the fills, the facts and the grading form
    expect(await screen.findByLabelText(`${A} trade`)).toHaveTextContent("ep_day");
    expect(await screen.findByTestId("trade-chart")).toHaveTextContent("2 bars, 1 fills");
    expect(await screen.findByLabelText("Grading form")).toHaveTextContent(`${A} trade`);
    expect(screen.getByRole("radiogroup", { name: "Conviction" })).toBeInTheDocument();
    rerender(<Journal tab="live" />);
    expect(await screen.findByLabelText("Real vs study")).toHaveTextContent("ep_day");
  });
});
