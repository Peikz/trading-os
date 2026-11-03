import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { dayOf, toSegment } from "../components/DrawChart";
import { mockApi } from "../test/mockApi";
import { Chart, hashTicker } from "./Chart";

const A = ["W", "Z", "Q", "W"].join(""); // synthetic

let drawn: { tool: string; onDraw?: (a: unknown, b: unknown, e: boolean) => void } = { tool: "" };
vi.mock("../components/DrawChart", async (orig) => ({
  ...(await orig<typeof import("../components/DrawChart")>()),
  DrawChart: (p: { tool: string; data: { candles: unknown[] }; onDraw?: (a: unknown, b: unknown, e: boolean) => void }) => {
    drawn = p;
    return <div data-testid="chart">{p.data.candles.length} bars · {p.tool}</div>;
  },
}));
vi.mock("../components/IntradayChart", () => ({
  IntradayChart: ({ data }: { data: { candles: unknown[] } }) => <div data-testid="intraday">{data.candles.length}</div>,
}));

const chart = {
  ticker: A,
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
  marks: [{ mark_id: "m1", kind: "anchor", anchor: "2026-06-01", label: "base" }],
  dates: ["2026-06-01", "2026-05-29"],
  tradingview: "https://www.tradingview.com/chart/?symbol=X",
  note: "Drag to pan.",
};

function routes() {
  return mockApi({
    "GET /api/chart/picks": [{ ticker: A, where: "EP-AH · pushed" }],
    [`GET /api/chart/${A}?`]: chart,
    [`POST /api/chart/${A}/lines`]: { mark_id: "m2" },
    [`POST /api/chart/${A}/anchors`]: { mark_id: "m3" },
    [`DELETE /api/chart/${A}/marks/`]: { removed: "m1" },
    [`GET /api/chart/${A}/notes`]: { notes: [], daily: [{ note_date: "2026-10-01", text: "day note", also: ["XZQX"] }] },
    [`POST /api/chart/${A}/notes`]: {
      notes: [{ note_id: "n1", note_date: "2026-10-02", text: "a note", written: "2026-10-02", edited: null }],
      daily: [],
    },
    [`GET /api/chart/${A}/intraday-days`]: { study_days: [], live: false, live_sessions: ["2026-10-30"], no_keys: "Live minute bars need the Alpaca keys." },
  });
}

describe("Chart", () => {
  it("reads the ticker from the hash", () => {
    expect(hashTicker(`#/chart?t=${A.toLowerCase()}`)).toBe(A);
    expect(hashTicker("#/chart")).toBe("");
  });

  it("charts a picked stock, draws a line with the tool and saves notes", async () => {
    const calls = routes();
    render(<Chart />);
    fireEvent.change(await screen.findByLabelText("Today's hits, watchlists, open positions"), { target: { value: A } });
    expect(await screen.findByTestId("chart")).toHaveTextContent("1 bars · none");
    expect(screen.getByText("From your daily notes (1)")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Draw a trend line (two clicks)"));
    expect(screen.getByTestId("chart")).toHaveTextContent("draw");
    drawn.onDraw?.({ time: "2026-05-29", price: 1 }, { time: "2026-06-01", price: 2 }, true);
    await waitFor(() => expect(calls.some((c) => c.url === `/api/chart/${A}/lines`)).toBe(true));
    const line = calls.find((c) => c.url === `/api/chart/${A}/lines`)!.body;
    expect(line).toEqual({ x0: "2026-05-29", y0: 1, x1: "2026-06-01", y1: 2, extend: true });

    fireEvent.change(screen.getByLabelText("New note"), { target: { value: "a note" } });
    fireEvent.click(screen.getByText("Save note"));
    expect(await screen.findByText("a note")).toBeInTheDocument();
  });

  it("asks for lines, AVWAPs and weekly bars, and says when live minutes need keys", async () => {
    const calls = routes();
    render(<Chart />);
    fireEvent.change(await screen.findByLabelText("Any ticker"), { target: { value: A } });
    await screen.findByTestId("chart");
    fireEvent.click(screen.getByText("MA200"));
    fireEvent.click(screen.getByText("highest high"));
    fireEvent.click(screen.getByText("Weekly"));
    await waitFor(() => {
      const last = calls.filter((c) => c.url.startsWith(`/api/chart/${A}?`)).pop()!;
      const q = new URLSearchParams(last.url.split("?")[1]);
      expect(q.get("lines")).toBe("MA10,MA20,MA50,MA200");
      expect(q.get("anchors")).toBe("highest high");
      expect(q.get("timeframe")).toBe("Weekly");
    });
    expect(screen.queryByLabelText("Tools")).not.toBeInTheDocument(); // drawing on daily bars only
    fireEvent.click(screen.getByLabelText("Intraday (minute bars)"));
    expect(await screen.findByText("Live minute bars need the Alpaca keys.")).toBeInTheDocument();
  });

  it("types in an anchor and removes a saved one", async () => {
    const calls = routes();
    render(<Chart />);
    fireEvent.change(await screen.findByLabelText("Any ticker"), { target: { value: A } });
    await screen.findByTestId("chart");
    fireEvent.click(screen.getByText("Type in a trend line or an anchor"));
    fireEvent.change(screen.getByLabelText("Anchor name (optional)"), { target: { value: "gap" } });
    fireEvent.click(screen.getByText("Save anchor"));
    await waitFor(() => expect(calls.some((c) => c.url === `/api/chart/${A}/anchors`)).toBe(true));
    expect(calls.find((c) => c.url === `/api/chart/${A}/anchors`)!.body).toEqual({ day: "2026-06-01", label: "gap" });
    fireEvent.click(screen.getByText("Remove"));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});

describe("DrawChart helpers", () => {
  it("turns chart times into days and measures the distance to a line", () => {
    expect(dayOf("2026-06-01")).toBe("2026-06-01");
    expect(dayOf({ year: 2026, month: 6, day: 1 })).toBe("2026-06-01");
    expect(dayOf(undefined)).toBeNull();
    expect(toSegment([5, 5], [0, 0], [10, 0])).toBe(5);
    expect(toSegment([20, 0], [0, 0], [10, 0])).toBe(10); // past the end: to the end point
  });
});
