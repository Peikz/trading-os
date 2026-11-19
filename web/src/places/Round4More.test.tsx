// Round 4, the rest: the shared table (sort, CSV), the settings (manual test runs, data folder), the
// Chart's one Notes tab and its Lines tab, the alerts' multi-select remove, and "Last screener
// result" in the Chart's lists. Synthetic tickers, built from letters.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ChartData, ChartListRow } from "../api";
import { Table, tableCsv } from "../components/Table";
import { PriceAlerts } from "../pages/Watchlists";
import { writeLastScreen } from "../shell/prefs";
import { TopBar } from "../shell/TopBar";
import { type Call, mockApi } from "../test/mockApi";
import { BottomPanel } from "./chart/BottomPanel";
import { useChartLists } from "./chart/lists";

const [A, B] = ["W", "X"].map((x) => [x, "Z", "Q", x].join(""));

beforeEach(() => {
  window.localStorage.clear();
  window.location.hash = "";
});

describe("The shared table", () => {
  const rows = [
    { name: "beta", amount: 20, memo: null },
    { name: "alpha", amount: 3, memo: "x" },
    { name: "gamma", amount: 100, memo: "y" },
  ];
  it("sorts by a header (numbers by value, blanks last) and clears on a third click", () => {
    render(<Table label="Things" columns={["name", "amount", "memo"]} rows={rows} />);
    const order = () =>
      within(screen.getByRole("table", { name: "Things" }))
        .getAllByRole("row")
        .slice(1)
        .map((r) => r.textContent?.slice(0, 5));
    fireEvent.click(screen.getByRole("button", { name: "amount" }));
    expect(order()).toEqual(["alpha", "beta2", "gamma"]);
    expect(screen.getByRole("columnheader", { name: /^amount/ })).toHaveAttribute("aria-sort", "ascending");
    fireEvent.click(screen.getByRole("button", { name: /^amount/ }));
    expect(order()[0]).toBe("gamma");
    fireEvent.click(screen.getByRole("button", { name: /^amount/ }));
    expect(order()[0]).toBe("beta2"); // cleared: the rows as they came
    fireEvent.click(screen.getByRole("button", { name: "memo" }));
    expect(order()[2]).toBe("beta2"); // the blank memo last
  });

  it("writes its CSV from the raw values", () => {
    expect(tableCsv(["name", "amount"], rows)).toBe(['"name","amount"', '"beta","20"', '"alpha","3"', '"gamma","100"'].join("\n"));
    render(<Table label="Things" columns={["name"]} rows={rows} />);
    expect(screen.getByRole("button", { name: "Download Things as CSV" })).toBeInTheDocument();
  });
});

describe("Settings", () => {
  const sync = {
    auto: true, setAuto: () => {}, busy: null, pull: null, push: null, unsaved: false, fresh: false,
    clearFresh: () => {}, pullNow: async () => {}, pushNow: async () => {},
  };
  it("shows the data folder, and the manual test runs toggle is sent with every request", async () => {
    const calls: { headers?: Record<string, string> }[] = [];
    mockApi({
      "GET /api/settings": { data_folder: "/data/trading-os-data" },
      "GET /api/market": { tiles: [], details: [] },
      "GET /api/system/status": { level: "ok", text: "fine", details: [] },
      "GET /api/health": { ok: true, runs: 12, latest: "2026-11-19_eod" },
    });
    const spy = vi.mocked(fetch);
    render(<TopBar place="today" sync={sync} onSearch={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByText("/data/trading-os-data")).toBeInTheDocument();
    expect(await screen.findByText("12 runs · session 2026-11-19")).toBeInTheDocument();
    const toggle = screen.getByRole("checkbox", { name: "Show manual test runs" });
    expect(toggle).toBeChecked(); // on, as in Streamlit
    const header = () => new Headers((spy.mock.calls.at(-1)?.[1] as RequestInit).headers).get("X-Manual-Runs");
    expect(header()).toBe("1");
    fireEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(JSON.parse(window.localStorage.getItem("trading-os.manual-runs") ?? "null")).toBe(false);
    await waitFor(() => expect(header()).toBe("0")); // the refresh re-reads with the new header
    void calls;
  });
});

describe("The alerts", () => {
  it("removes several at once", async () => {
    const sent: Call[] = mockApi({
      "GET /api/alerts": {
        directions: ["above", "below"], fired: [],
        alerts: [
          { alert_id: "a1", ticker: A, level: 10, direction: "above", note: "" },
          { alert_id: "a2", ticker: B, level: 20, direction: "below", note: "" },
          { alert_id: "a3", ticker: B, level: 30, direction: "above", note: "" },
        ],
      },
      "DELETE /api/alerts/": { directions: ["above", "below"], fired: [], alerts: [{ alert_id: "a3", ticker: B, level: 30, direction: "above", note: "" }] },
    });
    render(<PriceAlerts />);
    fireEvent.click(await screen.findByRole("checkbox", { name: `Select ${A} above 10` }));
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${B} below 20` }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove selected" }));
    await waitFor(() => expect(sent.filter((c) => c.method === "DELETE").map((c) => c.url)).toEqual(["/api/alerts/a1", "/api/alerts/a2"]));
    expect(await screen.findByText("Removed 2 alerts.")).toBeInTheDocument();
  });
});

const bars = (ticker: string): ChartData =>
  ({
    ticker, period: "2y", timeframe: "Daily", visible: null, lines: [], avwaps: [], trend: [], markers: [], levels: [],
    candles: [{ time: "2026-06-01", open: 1, high: 2, low: 0.5, close: 12.34, volume: 10 }],
    marks: [], dates: ["2026-06-01"], tradingview: "https://example.test/tv", note: "x", quick_anchors: {},
  }) as unknown as ChartData;

const nbIndex = {
  today: "2026-11-19",
  daily: [{ id: "d1", date: "2026-11-10", text: `held $${A} through the gap`, stocks: [A], tags: [] }],
  trades: [
    { id: "t1", status: "closed", ticker: A, direction: "long", entry_date: "2026-10-01", exit_date: "2026-10-20", setup: "EP", r: 1.5, pnl: 900, entry: 10, exit: 12, stop: 9, grade: "A", conviction: 3, text: "", tags: [], typed_tags: [] },
    { id: "open-1", status: "open", ticker: A, direction: "long", entry_date: "2026-11-05", exit_date: null, setup: "MA-surf", r: null, pnl: null, entry: 11, exit: null, stop: 10, grade: "", conviction: null, text: "", tags: [], typed_tags: [] },
  ],
  stocks: [{ ticker: A, notes: [{ note_id: "n1", date: "2026-11-03", text: "tight flag #base", tags: ["base"] }], tags: ["base"] }],
  pages: [], tags: [{ tag: "base", count: 1 }], tickers: [A],
};

describe("The Chart's Notes and Lines tabs", () => {
  const panel = (row?: ChartListRow, onSaved = () => {}) =>
    render(<BottomPanel symbol={A} data={bars(A)} row={row} open onToggle={() => {}} onMessage={() => {}} onSaved={onSaved} />);

  it("is one Notes tab: the stock's notes, its trades with R, grade and conviction, and the grading form", async () => {
    mockApi({
      "GET /api/notebook": nbIndex,
      [`GET /api/chart/${A}/notes`]: { notes: [{ note_id: "n1", note_date: "2026-11-03", text: "tight flag #base", written: "2026-11-03", edited: "2026-11-04" }], daily: [] },
      "GET /api/grades/signal/s1": { kind: "signal", grades: ["", "A", "B"], grade: "", notes: "", tags: "", conviction: null, convictions: [1, 2, 3], attachments: [] },
      "GET /api/symbols": { asof: "x", symbols: [[A, "Wizard"]] },
    });
    const row: ChartListRow = { ticker: A, grade: "A", setup: "EP 10:30", last: 1, chg_pct: 1, rvol: 1, signal_id: "s1" };
    panel(row);
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    expect(await screen.findByText(`Notes on ${A}`)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Journal" })).toHaveAttribute("href", `#/journal/notes?p=stock%3A${A}`);
    expect(await screen.findByText(/written 2026-11-03 · edited 2026-11-04/)).toBeInTheDocument();
    expect(screen.getByLabelText("Day of the note of 2026-11-03")).toHaveValue("2026-11-03");
    const trades = screen.getByRole("table", { name: `Trades in ${A}` });
    expect(within(trades).getByText("+1.50R")).toBeInTheDocument();
    expect(within(trades).getByText("3 high")).toBeInTheDocument();
    expect(within(trades).getByText("open")).toBeInTheDocument(); // the open trade too
    expect(within(trades).getByRole("link", { name: "Open the 2026-10-01 trade in the notebook" })).toHaveAttribute("href", "#/journal/notes?p=trade%3At1");
    expect(screen.getByRole("region", { name: "From your daily notes" })).toHaveTextContent("held $");
    expect(await screen.findByText("Grade this hit")).toBeInTheDocument(); // a scan hit today
    expect(screen.queryByRole("tab", { name: "Journal" })).not.toBeInTheDocument();
  });

  it("adds a horizontal line at a price and removes a saved line", async () => {
    let saved = [{ mark_id: "m1", kind: "line", text: "Level 12.50" }];
    const sent = mockApi({
      [`GET /api/chart/${A}/saved`]: () => saved,
      [`POST /api/chart/${A}/levels`]: () => {
        saved = [...saved, { mark_id: "m2", kind: "line", text: "Level 15.00" }];
        return { mark_id: "m2" };
      },
      [`DELETE /api/chart/${A}/marks/m1`]: () => {
        saved = saved.filter((m) => m.mark_id !== "m1");
        return { removed: "m1" };
      },
    });
    const onSaved = vi.fn();
    panel(undefined, onSaved);
    fireEvent.click(screen.getByRole("tab", { name: "Lines" }));
    const list = await screen.findByRole("list", { name: "Saved lines" });
    expect(within(list).getByText("Level 12.50")).toBeInTheDocument();
    const price = screen.getByLabelText("Level price");
    expect(price).toHaveValue(12.34); // the last close
    fireEvent.change(price, { target: { value: "15" } });
    fireEvent.click(screen.getByRole("button", { name: "Horizontal line" }));
    await waitFor(() => expect(sent.find((c) => c.url === `/api/chart/${A}/levels`)?.body).toEqual({ price: 15 }));
    expect(await within(await screen.findByRole("list", { name: "Saved lines" })).findByText("Level 15.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove: Level 12.50" }));
    await waitFor(() => expect(sent.some((c) => c.method === "DELETE")).toBe(true));
    expect(onSaved).toHaveBeenCalled();
  });
});

describe("Last screener result", () => {
  it("joins the Chart's lists once a screen's stock has been opened", async () => {
    mockApi({ "GET /api/chart-lists": { lists: [{ id: "hits", label: "Today's hits", group: "Today", count: 1 }] } });
    function Show() {
      const lists = useChartLists();
      return <p>{(lists ?? []).map((l) => `${l.group}:${l.label}:${l.count}`).join("|")}</p>;
    }
    const { unmount } = render(<Show />);
    expect(await screen.findByText("Today:Today's hits:1")).toBeInTheDocument();
    unmount();
    writeLastScreen([A, B]);
    render(<Show />);
    expect(await screen.findByText("Today:Today's hits:1|Screener:Last screener result:2")).toBeInTheDocument();
  });
});
