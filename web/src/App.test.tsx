import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { api } from "./api";
import { App } from "./App";
import { PUSH_AFTER_MS, useSync } from "./shell/useSync";
import { type Call, mockApi } from "./test/mockApi";

const A = ["W", "Z", "Q", "W"].join(""); // synthetic

vi.mock("./components/CandleChart", () => ({ CandleChart: () => <div data-testid="chart" /> }));

const market = {
  tiles: [],
  details: ["Breadth: 58% over the 50-day line"],
  mood: {
    level: "amber",
    word: "Cautious market",
    reasons: [
      { level: "amber", text: "QQQ light is yellow." },
      { level: "green", text: "Heat is warm: 64 stocks up 50 %+ in a quarter." },
      { level: "amber", text: "IBD: uptrend under pressure (4 of 6 sell days)." },
    ],
    quotes: [{ label: "SPY", value: "500.00", delta: "-0.4%" }],
  },
};

let sent: Call[] = [];
beforeEach(() => {
  window.location.hash = "";
  window.localStorage.clear();
  sent = mockApi({
    "GET /api/market": market,
    "GET /api/system/status": { level: "warn", text: "1 run missing", details: ["Tue 03 Nov mid"] },
    "GET /api/today": { scope: "graded", rows: [], hidden_c: 0, total: 0, next_scan: null },
    "GET /api/positions": { source: null, totals: {}, cards: [] },
    "GET /api/chart/picks": [{ ticker: A, where: "EP 10:30 · A+" }],
    "GET /api/guide": { text: "## How it works\n\nThe guide." },
    "POST /api/sync/pull": { ok: true, message: "Already up to date." },
    "POST /api/sync/push": { ok: true, message: "saved" },
    "POST /api/flags": { message: "ok" },
  });
});

describe("App", () => {
  it("shows the five places, the market in one word and why, and the status dot", async () => {
    render(<App />);
    const places = screen.getByRole("navigation", { name: "Places" });
    expect(within(places).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Today", "Stocks", "Market", "Journal", "Lab",
    ]);
    expect(within(places).getByText("Today")).toHaveAttribute("aria-current", "page");
    const pill = await screen.findByRole("button", { name: "Market: Cautious market. Show why" });
    fireEvent.click(pill);
    const why = screen.getByRole("dialog", { name: "Market" });
    expect(why).toHaveTextContent("QQQ light is yellow.");
    expect(why).toHaveTextContent("IBD: uptrend under pressure (4 of 6 sell days).");
    expect(why).toHaveTextContent("SPY500.00");
    fireEvent.click(await screen.findByRole("button", { name: "System status: 1 run missing" }));
    expect(screen.getByRole("dialog", { name: "System status" })).toHaveTextContent("Tue 03 Nov mid");
    expect(await screen.findByText("Nothing to buy today")).toBeInTheDocument();
  });

  it("opens a place's tab from the address and from Ctrl+K", async () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen.getByLabelText("Search stocks, pages and tabs", { selector: "input" });
    fireEvent.change(input, { target: { value: "guide" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(window.location.hash).toBe("#/lab/guide");
    act(() => window.dispatchEvent(new HashChangeEvent("hashchange")));
    expect(await screen.findByText("How it works")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Guide" })).toHaveAttribute("aria-selected", "true");
  });

  it("jumps to a stock from search", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Search stocks, pages and tabs" }));
    expect(await screen.findByText("EP 10:30 · A+")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "vzqv" } });
    fireEvent.click(screen.getByText("VZQV"));
    expect(window.location.hash).toBe("#/stocks?t=VZQV");
  });

  it("pulls on open and keeps the manual buttons in settings", async () => {
    render(<App />);
    await waitFor(() => expect(sent.some((c) => c.url === "/api/sync/pull")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const settings = screen.getByRole("dialog", { name: "Settings" });
    await waitFor(() => expect(settings).toHaveTextContent("Pull latest: done just now"));
    fireEvent.click(within(settings).getByRole("button", { name: /Save & push/ }));
    await waitFor(() => expect(sent.some((c) => c.url === "/api/sync/push")).toBe(true));
    fireEvent.click(within(settings).getByLabelText("Pull and save automatically"));
    expect(window.localStorage.getItem("trading-os.auto-sync")).toBe("off");
  });
});

function SyncProbe() {
  const s = useSync();
  return <p>{s.unsaved ? "unsaved" : "saved"}</p>;
}

describe("automatic Save & push", () => {
  it("pushes a while after a write, and never for a read-only POST", async () => {
    // Only the timers: Node's fetch reads a body with setImmediate, which must stay real
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    render(<SyncProbe />);
    await act(() => api.ticket({ ticker: A } as never).catch(() => undefined)); // computes only: no push
    await act(() => vi.advanceTimersByTimeAsync(PUSH_AFTER_MS + 100));
    expect(sent.some((c) => c.url === "/api/sync/push")).toBe(false);
    await act(() => api.flag(A, "Flag green")); // a write
    expect(screen.getByText("unsaved")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(PUSH_AFTER_MS - 1000));
    expect(sent.some((c) => c.url === "/api/sync/push")).toBe(false);
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(sent.some((c) => c.url === "/api/sync/push")).toBe(true);
    vi.useRealTimers();
    await waitFor(() => expect(screen.getByText("saved")).toBeInTheDocument());
  });
});
