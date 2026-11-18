import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { getActive, syncFromRoute } from "../shell/active";
import { mockApi } from "../test/mockApi";
import { ChartWorkspace } from "./ChartWorkspace";

// Synthetic tickers, built from letters so no real symbol appears here.
const [A, B, C] = ["W", "X", "Y"].map((x) => [x, "Z", "Q", x].join(""));

let drawn: { tool: string; onDraw?: (a: unknown, b: unknown, e: boolean) => void } = { tool: "" };
vi.mock("../components/DrawChart", async (orig) => ({
  ...(await orig<typeof import("../components/DrawChart")>()),
  DrawChart: (p: { tool: string; data: { ticker: string; candles: unknown[] }; onDraw?: (a: unknown, b: unknown, e: boolean) => void }) => {
    drawn = p;
    return <div data-testid="chart">{p.data.ticker} · {p.data.candles.length} bars · {p.tool}</div>;
  },
}));
vi.mock("../components/IntradayChart", () => ({ IntradayChart: () => <div /> }));

const chart = (ticker: string) => ({
  ticker,
  period: "2y",
  timeframe: "Daily",
  candles: [{ time: "2026-06-01", open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 }],
  lines: [],
  avwaps: [],
  trend: [],
  markers: [],
  levels: [],
  visible: null,
  quick_anchors: { "highest high": "2026-06-01" },
  marks: [],
  dates: ["2026-06-01"],
  tradingview: "https://www.tradingview.com/chart/?symbol=X",
  note: "Drag to pan.",
});

const row = (ticker: string, grade: string, chg: number | null, last: number | null = 10) => ({
  ticker, grade, setup: grade ? "EP 10:30" : "", last, chg_pct: chg, rvol: 2.5, signal_id: null,
});

function routes() {
  return mockApi({
    "GET /api/chart-lists": {
      lists: [
        { id: "hits", label: "Today's hits", group: "Today", count: 3 },
        { id: "wl:Leaders", label: "Leaders", group: "My lists", count: 1 },
      ],
    },
    "GET /api/chart-lists/hits": { id: "hits", label: "Today's hits", rows: [row(A, "A+", 1.5), row(B, "A", -2.25), row(C, "B", 4)] },
    "GET /api/chart-lists/wl%3ALeaders": { id: "wl:Leaders", label: "Leaders", rows: [row(C, "", null, null)] },
    "GET /api/sparks": { [A]: [{ time: "d1", open: 1, high: 1, low: 1, close: 1 }, { time: "d2", open: 1, high: 1, low: 1, close: 2 }] },
    "GET /api/chart/": (url: string) => chart(decodeURIComponent(url.split("?")[0].split("/")[3])),
    "POST /api/chart/": { mark_id: "m2" },
    "GET /api/watchlists/Flag%20green": { name: "Flag green", label: null, columns: [], rows: [], tv_list: "" },
    "GET /api/positions": { source: null, totals: {}, cards: [] },
    "GET /api/today": { scope: "all", rows: [], hidden_c: 0, total: 0, next_scan: null },
    "GET /api/journal/closed": { stats: {}, curve: [], trades: [], caption: "" },
    [`GET /api/chart/${A}/notes`]: { notes: [], daily: [] },
    [`GET /api/chart/${B}/notes`]: { notes: [], daily: [] },
  });
}

const urls = (calls: { method: string; url: string }[]) => calls.map((c) => c.url);

beforeEach(() => {
  window.location.hash = "#/chart";
  syncFromRoute(new URLSearchParams("s=&list="));
});

describe("ChartWorkspace", () => {
  it("opens the first stock of Today's hits and shows the list's columns", async () => {
    routes();
    render(<ChartWorkspace params={new URLSearchParams()} />);
    expect(await screen.findByTestId("chart")).toHaveTextContent(`${A} · 1 bars`);
    const table = await screen.findByRole("table", { name: "List: Today's hits" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Symbol", "Gr", "Last", "%", "20d", "RVOL", "Setup"]);
    expect(within(table).getByRole("button", { name: `Open ${A}` })).toHaveAttribute("aria-current", "true");
    expect(window.location.hash).toBe(`#/chart?s=${A}&list=hits`);
    expect(screen.getByText("Today's hits · 1 of 3")).toBeInTheDocument();
  });

  it("steps through the list with the arrow keys and J/K, and the chart follows without a reload", async () => {
    const calls = routes();
    render(<ChartWorkspace params={new URLSearchParams({ s: A, list: "hits" })} />);
    await screen.findByTestId("chart");
    fireEvent.keyDown(window, { key: "ArrowDown" });
    await waitFor(() => expect(screen.getByTestId("chart")).toHaveTextContent(`${B} · 1 bars`));
    fireEvent.keyDown(window, { key: "j" });
    await waitFor(() => expect(screen.getByTestId("chart")).toHaveTextContent(`${C} · 1 bars`));
    expect(screen.getByText("Today's hits · 3 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next stock" })).toBeDisabled(); // the end of the list
    fireEvent.keyDown(window, { key: "k" });
    await waitFor(() => expect(getActive().symbol).toBe(B));
    expect(window.location.hash).toBe(`#/chart?s=${B}&list=hits`);
    expect(urls(calls).filter((u) => u.startsWith(`/api/chart/${B}?`)).length).toBeGreaterThan(0);
    // typing in a field leaves the keys alone
    fireEvent.keyDown(screen.getByRole("combobox", { name: "List" }), { key: "ArrowUp" });
    expect(getActive().symbol).toBe(B);
  });

  it("switches list from the picker and sorts a column", async () => {
    const calls = routes();
    render(<ChartWorkspace params={new URLSearchParams({ s: A, list: "hits" })} />);
    const table = await screen.findByRole("table", { name: "List: Today's hits" });
    const order = () => within(table).getAllByRole("button", { name: /^Open / }).map((b) => b.textContent);
    expect(order()).toEqual([A, B, C]);
    fireEvent.click(within(table).getByRole("button", { name: "%" }));
    expect(order()).toEqual([C, A, B]); // best change first
    fireEvent.click(within(table).getByRole("button", { name: "%" }));
    expect(order()).toEqual([B, A, C]);
    fireEvent.click(within(table).getByRole("button", { name: "%" }));
    expect(order()).toEqual([A, B, C]); // a third click clears the sort
    fireEvent.change(screen.getByRole("combobox", { name: "List" }), { target: { value: "wl:Leaders" } });
    await screen.findByRole("table", { name: "List: Leaders" });
    expect(urls(calls)).toContain("/api/chart-lists/wl%3ALeaders");
    expect(window.location.hash).toContain("list=wl%3ALeaders");
  });

  it("asks for lines, AVWAPs and weekly bars, and draws trend lines on the daily bars only", async () => {
    const calls = routes();
    render(<ChartWorkspace params={new URLSearchParams({ s: A, list: "hits" })} />);
    await screen.findByTestId("chart");
    fireEvent.click(screen.getByRole("button", { name: "Draw a trend line (two clicks)" }));
    expect(screen.getByTestId("chart")).toHaveTextContent("draw");
    drawn.onDraw?.({ time: "2026-05-29", price: 1 }, { time: "2026-06-01", price: 2 }, true);
    await waitFor(() => expect(calls.some((c) => c.url === `/api/chart/${A}/lines`)).toBe(true));
    expect(calls.find((c) => c.url === `/api/chart/${A}/lines`)!.body).toEqual({ x0: "2026-05-29", y0: 1, x1: "2026-06-01", y1: 2, extend: true });
    expect(await screen.findByRole("status")).toHaveTextContent("Line saved.");

    fireEvent.click(screen.getByRole("button", { name: /Indicators/ }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Indicators" })).getByLabelText("MA200"));
    fireEvent.click(screen.getByRole("button", { name: /^Lines/ }));
    fireEvent.click(screen.getByText("highest high"));
    fireEvent.click(screen.getByRole("button", { name: "W" }));
    await waitFor(() => {
      const last = calls.filter((c) => c.url.startsWith(`/api/chart/${A}?`)).pop()!;
      const q = new URLSearchParams(last.url.split("?")[1]);
      expect(q.get("lines")).toBe("MA10,MA20,MA50,MA200");
      expect(q.get("anchors")).toBe("highest high");
      expect(q.get("timeframe")).toBe("Weekly");
    });
    expect(screen.queryByRole("group", { name: "Tools" })).not.toBeInTheDocument();
  });

  it("shows the stock's plan, position and journal in the bottom panel, and collapses it", async () => {
    routes();
    render(<ChartWorkspace params={new URLSearchParams({ s: A, list: "hits" })} />);
    await screen.findByTestId("chart");
    expect(await screen.findByText(`No scan hit for ${A} in the newest runs, so no plan.`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Position" }));
    expect(await screen.findByText(`No open position in ${A}.`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Journal" }));
    expect(await screen.findByText(`No closed trades in ${A} yet.`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide the stock panel" }));
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide the list" }));
    expect(screen.queryByRole("complementary", { name: "List panel" })).not.toBeInTheDocument();
  });

  it("on a phone: step arrows in the header and the list as a sheet", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("640"),
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    routes();
    render(<ChartWorkspace params={new URLSearchParams({ s: A, list: "hits" })} />);
    await screen.findByTestId("chart");
    fireEvent.click(screen.getByRole("button", { name: "Next stock" }));
    await waitFor(() => expect(getActive().symbol).toBe(B));
    const sheet = screen.getByRole("region", { name: "List sheet" });
    expect(sheet).toHaveAttribute("data-stop", "peek");
    fireEvent.click(within(sheet).getByRole("button", { name: /List sheet: peek/ }), { detail: 0 });
    expect(sheet).toHaveAttribute("data-stop", "half");
    fireEvent.click(within(sheet).getByRole("button", { name: `Open ${C}` }));
    await waitFor(() => expect(getActive().symbol).toBe(C));
    vi.unstubAllGlobals();
  });
});
