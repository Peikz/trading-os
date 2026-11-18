import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { Practice } from "./Practice";

// Synthetic: no real stock, price or result here.
vi.mock("../components/DrawChart", () => ({
  DrawChart: ({ data }: { data: { candles: unknown[]; markers: { text: string }[]; labels?: unknown } }) => (
    <div data-testid="chart">
      {data.candles.length} bars · {data.markers.map((m) => m.text).join("+") || "no markers"} ·{" "}
      {data.labels ? "relative days" : "real dates"}
    </div>
  ),
}));

const stats = (answered: number) => ({
  pool: "practice",
  answered,
  by_choice: {
    skip: { count: 0, mean_r: null },
    "1": { count: 0, mean_r: null },
    "2": { count: 0, mean_r: null },
    "3": { count: answered, mean_r: answered ? 3 : null },
  },
  by_shown: {
    blind: { answered: 0, picks_r: 0, equal_r: 0, picks_r_per_signal: null, equal_r_per_signal: null },
    shown: { answered, picks_r: 4.5 * answered, equal_r: 3 * answered, picks_r_per_signal: 4.5, equal_r_per_signal: 3 },
  },
  picks_r: 4.5 * answered,
  equal_r: 3 * answered,
  picks_r_per_signal: answered ? 4.5 : null,
  equal_r_per_signal: answered ? 3 : null,
  big: { total: 0, taken: 0, skipped: 0 },
  losers: { total: 0, taken: 0, skipped: 0 },
  remaining: 1 - answered,
  pool_size: 1,
});

const chart = (n: number, markers: { text: string }[], labels: unknown = null) => ({
  candles: Array.from({ length: n }, (_, i) => ({ time: `d${i}`, open: 1, high: 1, low: 1, close: 1, volume: 1 })),
  markers, labels, lines: [], avwaps: [], trend: [], levels: [], visible: null,
});

function setup() {
  let answered = false;
  const calls = mockApi({
    "GET /api/practice/answers": () =>
      answered
        ? [{ signal_id: "p1", pool: "practice", ticker: "WZQW", setup_name: "ep_day", choice: "3", net_r: 3, entry_date: "2024-05-24", hold_days: 5, answered: "2026-11-18", shown: false, note: "clean" }]
        : [],
    "GET /api/practice/next": () => ({ signal_id: answered ? null : "p1" }),
    "GET /api/practice/signal/p1": (url: string) => ({
      signal_id: "p1",
      pool: "practice",
      answered,
      shown: url.includes("shown=true"),
      ticker: answered || url.includes("shown=true") ? "WZQW" : null,
      facts: [{ label: "Setup", value: "ep_day" }, { label: "Stop distance", value: "7.0 %" }],
      chart: answered ? chart(38, [{ text: "entry" }, { text: "exit" }]) : chart(30, [], url.includes("shown=true") ? null : { d0: "day -30" }),
      result: answered
        ? { choice: "3", pool: "practice", net_r: 3, pick_r: 4.5, hold_days: 5, entry_date: "2024-05-24", ticker: "WZQW", setup: "ep_day", answered_at: null, shown: false, note: "clean" }
        : null,
    }),
    "POST /api/practice/answer": () => {
      answered = true;
      return { result: {} };
    },
    "PUT /api/practice/note": { saved: true },
    "GET /api/practice": () => ({
      available: true,
      pools: [{ id: "practice", label: "Practice 2016-21" }, { id: "exam", label: "Exam 2022-26" }],
      stats: { practice: stats(answered ? 1 : 0), exam: { ...stats(0), pool: "exam" } },
      lines: ["MA10", "MA20", "MA50", "EMA9", "EMA21"],
    }),
  });
  return calls;
}

describe("Practice", () => {
  it("shows the chart up to the entry, answers once and reveals the trade", async () => {
    const calls = setup();
    render(<Practice />);
    const card = await screen.findByLabelText("The signal");
    // Shown by default in the practice pool: real dates; the answers wait for you
    expect(await within(card).findByTestId("chart")).toHaveTextContent("30 bars · no markers");
    expect(within(card).getByLabelText("Facts known at the entry")).toHaveTextContent("Stop distance7.0 %");
    fireEvent.change(within(card).getByLabelText("Note"), { target: { value: "clean" } });
    const group = within(card).getByRole("group", { name: "Your answer" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual(["Skip", "1", "2", "3"]);
    fireEvent.click(within(group).getByRole("button", { name: "3" }));
    expect(await screen.findByRole("status")).toHaveTextContent("net +3.00 R in 5 days · your pick 3 = +4.50 R");
    const sent = calls.find((c) => c.url === "/api/practice/answer")!.body;
    expect(sent).toEqual({ signal_id: "p1", pool: "practice", choice: "3", note: "clean", shown: true });
    expect(await screen.findByTestId("chart")).toHaveTextContent("38 bars · entry+exit");
    expect(screen.queryByRole("group", { name: "Your answer" })).not.toBeInTheDocument();
    // Your numbers and your answered signals update
    await waitFor(() => expect(screen.getByLabelText("Your answered signals")).toHaveTextContent("clean"));
    expect(screen.getByText(/1 answered, 0 left of 1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Every signal in this pool is answered.")).toBeInTheDocument();
  });

  it("hides the stock and the dates when the switch is off", async () => {
    setup();
    render(<Practice />);
    const card = await screen.findByLabelText("The signal");
    fireEvent.click(screen.getByLabelText("Show stock and date"));
    await waitFor(() => expect(within(card).getByTestId("chart")).toHaveTextContent("relative days"));
    expect(within(card).queryByText("WZQW")).not.toBeInTheDocument();
  });

  it("says so when there is no practice export", async () => {
    mockApi({ "GET /api/practice/answers": [], "GET /api/practice": { available: false, pools: [], stats: {}, lines: [] } });
    render(<Practice />);
    expect(await screen.findByText(/No practice data yet/)).toBeInTheDocument();
  });
});
