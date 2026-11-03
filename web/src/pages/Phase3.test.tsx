import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { Guide } from "./Guide";
import { Journal } from "./Journal";
import { Market, Rotation } from "./Market";

vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  createChart: () => ({
    addLineSeries: () => ({ setData: () => {} }),
    timeScale: () => ({ fitContent: () => {} }),
    remove: () => {},
  }),
}));

const t = (columns: string[], rows: Record<string, unknown>[]) => ({ columns, rows, total: rows.length });
const X = ["X", "Z", "Q", "X"].join(""); // synthetic

const page = {
  empty: false,
  tiles: [{ label: "QQQ light", value: "🟢 GREEN", delta: null }, { label: "SPY", value: "500.00", delta: "+0.5%" }],
  ibd: t([], []),
  ibd_caption: "O'Neil.",
  heat: {
    bands: [{ band: "cool", label: "under 20" }, { band: "hot", label: "60+" }],
    now: "cool",
    count: 12,
    band: "cool",
    table: t(["setup", "verdict"], [{ setup: "EP 10:30", verdict: "✅ held" }]),
    caption: "Net R a trade after costs.",
  },
  periods: ["Today", "1 month"],
  period: "1 month",
  groups: ["Index", "Sector", "Theme"],
  picked: ["Index", "Sector", "Theme"],
  sectors: t(["name", "ticker"], [{ name: "Synthetic", ticker: X }]),
  sector_caption: "saved 2026-10-30.",
  rotation: [{ ticker: X, name: "Synthetic", group: "Sector", x: -3, y: 2 }],
  back: "1 week",
  industries: { top: t(["rank", "industry"], [{ rank: 1, industry: "Software" }]), climbing: t([], []), caption: "Ranked." },
  breadth: t(["session_date", "light"], [{ session_date: "2026-10-30", light: "GREEN" }]),
  ratios: [{ time: "2026-10-30", ratio_5d: 1.2, ratio_10d: 1.1 }],
};

describe("Market", () => {
  it("shows the tiles, the setups at the heat, sectors and industries, and asks for another band", async () => {
    const calls = mockApi({ "GET /api/market/page": page });
    render(<Market />);
    expect(await screen.findByText("Cool market: scan count 12 (under 20)")).toBeInTheDocument();
    expect(screen.getByText("🟢 GREEN")).toBeInTheDocument();
    expect(screen.getByLabelText("Setups at this heat", { selector: "table" })).toHaveTextContent("✅ held");
    expect(screen.getByLabelText("Indexes, sectors and themes")).toHaveTextContent(X);
    expect(screen.getByLabelText("Top 15 industries")).toHaveTextContent("Software");
    fireEvent.click(screen.getByText("hot (60+)"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("band=hot"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Theme" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("groups=Index%2CSector"))).toBe(true));
  });

  it("says when there is no breadth yet", async () => {
    mockApi({ "GET /api/market/page": { empty: true } });
    render(<Market />);
    expect(await screen.findByText(/Breadth rows start with the first scheduled EOD run/)).toBeInTheDocument();
  });

  it("puts a sector behind SPY over the month and ahead this week in Improving", () => {
    render(<Rotation points={[{ ticker: X, group: "Sector", x: -3, y: 2 }]} />);
    const dot = screen.getByText(X);
    const [x, y] = [Number(dot.getAttribute("x")), Number(dot.getAttribute("y"))];
    expect(x).toBeLessThan(320); // left of the middle of 640
    expect(y).toBeLessThan(210); // above the middle of 420
  });
});

describe("Guide", () => {
  it("renders the guide", async () => {
    mockApi({ "GET /api/guide": { text: "## 1. What it is\n\nA scanner." } });
    render(<Guide />);
    expect(await screen.findByRole("heading", { name: "1. What it is" })).toBeInTheDocument();
  });
});

describe("Journal, phase 3", () => {
  it("adds, filters and deletes daily notes", async () => {
    const notes = {
      notes: [{ note_id: "d1", note_date: "2026-10-30", text: `Watching $${X}`, tags: [X] }],
      tags: [X],
      days: [7, 30, 90, 365, 3650],
      caption: "A note about the day.",
      kept: "Kept for good.",
    };
    const calls = mockApi({
      "GET /api/journal/open": { totals: { positions: 0, open_pnl: 0, at_risk_usd: 0, at_risk_pct: null }, rows: [], plan: [], plan_day: null },
      "GET /api/journal/daily-notes": notes,
      "POST /api/journal/daily-notes": { note_id: "d2" },
      "DELETE /api/journal/daily-notes/": { removed: "d1" },
    });
    render(<Journal />);
    fireEvent.click(screen.getByRole("tab", { name: "Daily notes" }));
    expect(await screen.findByText(`Watching $${X}`)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Daily note"), { target: { value: "Quiet day" } });
    fireEvent.change(screen.getByLabelText("Stocks (comma or space separated)"), { target: { value: X } });
    fireEvent.click(screen.getByText("Save note"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ text: "Quiet day", tags: X });
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: X } });
    fireEvent.click(screen.getByText("all"));
    await waitFor(() => expect(calls.some((c) => c.url.includes(`tag=${X}`) && c.url.includes("days=3650"))).toBe(true));
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("imports a broker CSV", async () => {
    const calls = mockApi({
      "GET /api/journal/open": { totals: { positions: 0, open_pnl: 0, at_risk_usd: 0, at_risk_pct: null }, rows: [], plan: [], plan_day: null },
      "POST /api/journal/import": { message: "2 new fills, 1 trade" },
    });
    render(<Journal />);
    fireEvent.click(screen.getByText("Import broker fills (CSV)"));
    const file = new File(["trade_date,ticker\n"], "fills.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("Fills export"), { target: { files: [file] } });
    fireEvent.click(screen.getByText("Import"));
    expect(await screen.findByText("2 new fills, 1 trade")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ name: "fills.csv", content: "trade_date,ticker\n" });
  });
});
