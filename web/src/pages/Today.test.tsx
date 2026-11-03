import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { BoardRow, Today as TodayData } from "../api";
import { pushTickers, Today } from "./Today";

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

const calls: string[] = [];
beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      const body = url.startsWith("/api/today")
        ? today
        : url.startsWith("/api/market")
          ? { tiles: [{ label: "QQQ light", value: "🟢 GREEN", delta: null }], details: [] }
          : { ticker: url.split("/")[3].split("?")[0], tf: "1D", candles: [], lines: [] };
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
});

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
    await waitFor(() => expect(calls.some((u) => u.includes("tf=1W"))).toBe(true));
  });

  it("asks for MA 10/20/50 by default", async () => {
    render(<Today />);
    await screen.findByText("1 of 2 · 1 C hidden");
    await waitFor(() => expect(calls.some((u) => u.startsWith(`/api/bars/${B}`))).toBe(true));
    const bars = calls.find((u) => u.startsWith(`/api/bars/${B}`))!;
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

describe("pushTickers", () => {
  it("reads a push link's stocks", () => {
    expect(pushTickers(`?push=ah&t=${A},${B}`)).toEqual([A, B]);
    expect(pushTickers("")).toEqual([]);
  });
});
