import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { type Call, mockApi } from "../test/mockApi";
import { Stocks } from "./Stocks";

// Synthetic tickers, built from letters so no real symbol appears here.
const [A, B] = ["W", "X"].map((x) => [x, "Z", "Q", x].join(""));

vi.mock("../components/DrawChart", async (orig) => ({
  ...(await orig<typeof import("../components/DrawChart")>()),
  DrawChart: ({ data }: { data: { ticker: string } }) => <div data-testid="full-chart">{data.ticker}</div>,
}));

const meta = {
  fields: {
    adr20_pct: { label: "ADR % (20d)", kind: "pct", group: "Volatility" },
    rs_pct: { label: "RS percentile (1-99)", kind: "num", group: "Performance" },
    chg_pct: { label: "Change %", kind: "pct", group: "Price & volume" },
  },
  ops: { num: [">=", "<=", "between"], pct: [">=", "<=", "between"], money: [], bool: [], text: [] },
  shown: ["ticker", "chg_pct", "adr20_pct", "rs_pct"],
  examples: {
    "Momentum leaders": {
      filters: [{ field: "rs_pct", op: ">=", value: 90 }, { field: "adr20_pct", op: ">=", value: 4 }],
      sort: "rs_pct",
      descending: true,
    },
  },
  saved: {},
  labels: {},
};

const result = (tickers: string[], grade?: string) => ({
  count: tickers.length,
  when: "the 03 Nov close",
  summary: "",
  columns: [...(grade ? ["grade"] : []), "ticker", "chg_pct", "adr20_pct", "rs_pct"],
  rows: tickers.map((t, i) => ({ ticker: t, ...(grade ? { grade } : {}), chg_pct: 1.5 - i * 3, adr20_pct: 5.25, rs_pct: 95 })),
  tickers,
  tv_list: tickers.join(","),
  signal_ids: Object.fromEntries(tickers.map((t) => [t, `sig-${t}`])),
});

let sent: Call[] = [];
beforeEach(() => {
  sent = mockApi({
    "GET /api/screener/meta": meta,
    "GET /api/watchlists": { lists: ["Leaders"], flags: ["Flag green"] },
    "GET /api/watchlists/Leaders": {
      name: "Leaders", label: "2026-11-03 · EOD", columns: ["ticker", "close", "in_scans", "note"],
      rows: [{ ticker: A, close: 10, in_scans: "ep_am", note: "base" }, { ticker: B, close: 20, in_scans: "", note: "" }], tv_list: `NASDAQ:${A}`,
    },
    "GET /api/watchlists/Flag%20green": { name: "Flag green", label: null, columns: [], rows: [], tv_list: "" },
    "POST /api/watchlists/Leaders/add": { kind: "success", added: [B], already: [], unknown: [], lines: [`Added to **Leaders**: ${B}`] },
    "POST /api/watchlists/Leaders/remove": { name: "Leaders", label: null, columns: [], rows: [], tv_list: "" },
    "GET /api/runs": [{ id: "2026-11-03_eod", label: "2026-11-03 · EOD", session: "2026-11-03", slot: "eod", kind: "scheduled", has_universe: true, has_breadth: true }],
    "GET /api/runs/2026-11-03_eod/scans": { run: "x", label: "x", scans: { ep_am: { label: "EP 10:30", pushed: true, count: 2, hits: [] } } },
    "POST /api/screener/run": (_: string, b: unknown) => {
      const body = b as { source: string };
      return body.source === "hits" ? result([A, B], "A+") : result([A, B]);
    },
    "GET /api/sparks": { [A]: [{ time: "2026-11-03", open: 1, high: 2, low: 0.5, close: 1.5 }], [B]: [] },
    "PUT /api/screens/": { Mine: meta.examples["Momentum leaders"] },
    "GET /api/chart/": { ticker: A, period: "2y", timeframe: "Daily", candles: [{ time: "2026-11-03", open: 1, high: 2, low: 0.5, close: 1.5, volume: 1 }], lines: [], avwaps: [], trend: [], markers: [], levels: [], visible: null, quick_anchors: {}, marks: [], dates: [], tradingview: "#", note: "" },
    [`GET /api/chart/${A}/notes`]: { notes: [], daily: [] },
    [`GET /api/chart/${A}/intraday-days`]: { study_days: [], live: false, live_sessions: [], no_keys: "" },
    "GET /api/grades/signal/": { kind: "signal", ref_id: `sig-${A}`, grades: ["", "A+"], grade: "", notes: "", tags: "", attachments: [] },
  });
});
const screens = () => sent.filter((c) => c.url === "/api/screener/run").map((c) => c.body as Record<string, unknown>);

describe("Stocks", () => {
  it("lists the sources and opens your first list, filtered through the screener", async () => {
    render(<Stocks params={new URLSearchParams()} />);
    const nav = await screen.findByRole("navigation", { name: "Sources" });
    expect(within(nav).getByText("My lists")).toBeInTheDocument();
    expect(within(nav).getByText("Screens")).toBeInTheDocument();
    expect(await within(nav).findByText("EP 10:30")).toBeInTheDocument();
    expect(within(nav).getByText("Momentum leaders")).toBeInTheDocument();
    await waitFor(() => expect(screens().some((b) => b.source === "list" && b.watchlist === "Leaders")).toBe(true));
    expect(await screen.findByText("2 stocks · the 03 Nov close")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Open ${A}` })).toHaveTextContent("Range 5.3%");
  });

  it("shows a screen's filters as chips, drops one, and saves the screen", async () => {
    render(<Stocks params={new URLSearchParams({ src: "example:Momentum leaders" })} />);
    const chips = await screen.findByLabelText("Filters");
    expect(await within(chips).findByText("RS >= 90")).toBeInTheDocument();
    expect(within(chips).getByText("Daily range % >= 4")).toBeInTheDocument();
    await waitFor(() => expect(screens().some((b) => (b.filters as unknown[]).length === 2)).toBe(true));
    fireEvent.click(within(chips).getByRole("button", { name: "Remove filter: RS >= 90" }));
    await waitFor(() => expect(screens().at(-1)!.filters).toEqual([{ field: "adr20_pct", op: ">=", value: 4 }]));
    fireEvent.click(within(chips).getByText("Filter"));
    await waitFor(() => expect((screens().at(-1)!.filters as unknown[]).length).toBe(2));
    fireEvent.click(await screen.findByText("Save screen"));
    fireEvent.change(screen.getByLabelText("Screen name"), { target: { value: "Mine" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent.some((c) => c.method === "PUT" && c.url === "/api/screens/Mine")).toBe(true));
  });

  it("switches to the table and opens a stock's full chart in place", async () => {
    window.location.hash = "#/stocks";
    const { rerender } = render(<Stocks params={new URLSearchParams({ src: "all" })} />);
    await screen.findByText("2 stocks · the 03 Nov close");
    fireEvent.click(screen.getByRole("button", { name: /Table/ }));
    const table = await screen.findByLabelText("Results");
    expect(within(table).getByText("Daily range %")).toHaveAttribute("title", "ADR %: average daily range over 20 days");
    fireEvent.click(within(table).getByText(A));
    expect(window.location.hash).toBe(`#/stocks?src=all&t=${A}`);
    rerender(<Stocks params={new URLSearchParams({ src: "all", t: A })} />);
    expect(await screen.findByTestId("full-chart")).toHaveTextContent(A);
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Watch: add/ }));
    await waitFor(() => expect(sent.find((c) => c.url === "/api/flags")?.body).toEqual({ ticker: A, name: "Flag green" }));
    window.localStorage.clear();
  });

  it("grades a scan hit under its chart", async () => {
    render(<Stocks params={new URLSearchParams({ src: "scan:ep_am", t: A })} />);
    await waitFor(() => expect(screens().some((b) => b.source === "hits" && b.scan === "ep_am")).toBe(true));
    expect(await screen.findByText("Grade this hit")).toBeInTheDocument();
    expect(await screen.findByLabelText("Grading form")).toHaveTextContent(`Grade ${A} · EP 10:30`);
  });

  it("adds to a list and removes from it", async () => {
    render(<Stocks params={new URLSearchParams({ src: "list:Leaders" })} />);
    await screen.findByText("2 stocks · the 03 Nov close");
    fireEvent.change(screen.getByLabelText("Add tickers"), { target: { value: B } });
    fireEvent.click(screen.getByText("Add to list"));
    expect(await screen.findByRole("status")).toHaveTextContent(`Added to Leaders: ${B}`);
    fireEvent.click(screen.getByRole("button", { name: `Remove ${A} from the list` }));
    await waitFor(() =>
      expect(sent.find((c) => c.url === "/api/watchlists/Leaders/remove")?.body).toEqual({ tickers: [A] }),
    );
  });
});
