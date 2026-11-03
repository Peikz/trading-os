import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { LiveResults } from "./LiveResults";
import { Research } from "./Research";
import { Scans } from "./Scans";
import { SystemHealth } from "./SystemHealth";

const A = ["W", "Z", "Q", "W"].join(""); // synthetic
const t = (columns: string[], rows: Record<string, unknown>[]) => ({ columns, rows, total: rows.length });

vi.mock("../components/DrawChart", () => ({ DrawChart: () => <div data-testid="chart" /> }));

describe("Research", () => {
  it("shows a strategy's rules as markdown and switches sections", async () => {
    const calls = mockApi({
      "GET /api/research/strategy-rules": {
        labels: ["EP 10:30", "VCP"],
        label: "EP 10:30",
        heading: "Live scan `ep_am` · on",
        rules: "Buys **the gap**.\n\n- one\n- two",
        settings: [{ setting: "min_gap_pct", value: "4" }],
        heat: [],
        heat_note: null,
      },
      "GET /api/research/notes": { names: ["2026-10-20-study"], name: "2026-10-20-study", text: "# A study" },
    });
    render(<Research />);
    expect(await screen.findByText("the gap")).toBeInTheDocument();
    expect(screen.getByLabelText("The numbers")).toHaveTextContent("min_gap_pct");
    fireEvent.change(screen.getByLabelText("Strategy"), { target: { value: "VCP" } });
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("?label=VCP"))).toBe(true));
    fireEvent.click(screen.getByRole("tab", { name: "Study notes" }));
    expect(await screen.findByRole("heading", { name: "A study" })).toBeInTheDocument();
  });

  it("filters the History and opens an event's chart", async () => {
    const calls = mockApi({
      "POST /api/research/history": {
        empty: false,
        graded: { summary: t([], []), by_grade: t([], []), caption: "" },
        caption: "Every alert-tier hit.",
        strategies: ["mb_up", "qm_gainers"],
        years: [2025, 2026],
        picked: ["mb_up", "qm_gainers"],
        chosen_years: [2025, 2026],
        ep_flags: [],
        splits: ["none", "year"],
        split: "none",
        count: 20,
        summary: t(["strategy", "events"], [{ strategy: "mb_up", events: 10 }]),
        summary_caption: "",
        compared: t(["group", "exit"], [{ group: "mb_up", exit: "r_5d" }]),
        one: "mb_up",
        events: t(["session_date", "ticker", "stop"], [{ session_date: "2026-07-01", ticker: A, stop: 9 }]),
      },
      "GET /api/research/history/event": { candles: [{ time: "2026-07-01" }] },
    });
    render(<Research />);
    fireEvent.click(await screen.findByRole("tab", { name: "History" }));
    expect(await screen.findByText("20 events")).toBeInTheDocument();
    expect(screen.getByText("Not built yet (data repo release grading-10y).")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Split by"), { target: { value: "year" } });
    await waitFor(() => expect(calls.some((c) => (c.body as { split?: string })?.split === "year")).toBe(true));
    fireEvent.change(screen.getByLabelText("Event chart"), { target: { value: "0" } });
    expect(await screen.findByTestId("chart")).toBeInTheDocument();
    const ev = calls.find((c) => c.url.startsWith("/api/research/history/event"))!;
    expect(new URLSearchParams(ev.url.split("?")[1]).get("stop")).toBe("9");
  });

  it("says when a study isn't published", async () => {
    mockApi({
      "GET /api/research/strategy-rules": { labels: ["X"], label: "X", heading: "", rules: "", settings: [], heat: [], heat_note: null },
      "GET /api/research/entries": { published: false },
      "GET /api/research/regime": { published: false },
    });
    render(<Research />);
    fireEvent.click(await screen.findByRole("tab", { name: "Entries & exits" }));
    expect(await screen.findByText(/10-year minute study hasn't been published/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Market regime" }));
    expect(await screen.findByText(/regime study hasn't been published/)).toBeInTheDocument();
  });
});

describe("Live results and System health", () => {
  it("shows live grades and the graded signals", async () => {
    mockApi({
      "GET /api/live/grades": {
        compare: t(["grade", "closed"], [{ grade: "A+", closed: 0 }]),
        gaps: t([], []),
        signals: t([], []),
        monthly: null,
        caption: "'too few trades yet'",
      },
      "GET /api/live/graded": t(["ref_id", "grade"], [{ ref_id: "s1", grade: "A" }]),
    });
    render(<LiveResults />);
    expect(await screen.findByLabelText("Grades live vs study")).toHaveTextContent("A+");
    expect(screen.getByText(/None yet: a closed journal trade/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Signals you graded" }));
    expect(await screen.findByLabelText("Signals you graded")).toHaveTextContent("s1");
  });

  it("shows the run grid and asks GitHub on request", async () => {
    mockApi({
      "GET /api/system/jobs": {
        grid: t(["session", "eod"], [{ session: "2026-10-30", eod: "✅" }]),
        freshness: t([], []),
        failures: t([], []),
        cache: { used_gb: 0.1, limit_gb: 2 },
      },
      "GET /api/system/github": { answered: false },
    });
    render(<SystemHealth />);
    expect(await screen.findByLabelText("Runs per session")).toHaveTextContent("✅");
    expect(screen.getByText("No failure logs.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Load the latest runs from GitHub"));
    expect(await screen.findByText(/No answer from GitHub/)).toBeInTheDocument();
  });
});

describe("Scans", () => {
  const page = {
    caption: "Every scan.",
    rows: [{ scan: "EP-Day", on: true, grade: "A+ at 3+ points", key: "ep_day" }],
    names: [{ key: "ep_day", label: "EP-Day" }],
    writable: true,
    checkout: true,
    note: null,
  };
  const form = {
    name: "ep_day",
    label: "EP-Day",
    enabled: true,
    action: "push",
    push: null,
    numbers: [{ key: "min_gap_pct", value: 8, kind: "float" }],
    flags: [],
    push_label: "",
    note: "",
    push_slots: ["at its run", "next pre-market", "both"],
  };

  it("checks and saves a change and shows the diff", async () => {
    const calls = mockApi({
      "GET /api/scans": page,
      "GET /api/scans/ep_day/form": form,
      "POST /api/scans/ep_day": { saved: true, message: "Saved EP-Day.", diff: "-  min_gap_pct: 8\n+  min_gap_pct: 9" },
    });
    render(<Scans />);
    expect(await screen.findByLabelText("Scans")).toHaveTextContent("EP-Day");
    fireEvent.change(await screen.findByLabelText("min_gap_pct"), { target: { value: "9" } });
    fireEvent.click(screen.getByText("Check and save"));
    expect(await screen.findByText("Saved EP-Day.")).toBeInTheDocument();
    expect(screen.getByText(/min_gap_pct: 9/)).toBeInTheDocument();
    const body = calls.find((c) => c.method === "POST")!.body as { values: Record<string, unknown> };
    expect(body.values.min_gap_pct).toBe(9);
  });

  it("is view only where the config can't be written", async () => {
    mockApi({
      "GET /api/scans": { ...page, writable: false, note: "View only here." },
      "GET /api/scans/ep_day/form": form,
    });
    render(<Scans />);
    expect(await screen.findByText("View only here.")).toBeInTheDocument();
    expect(await screen.findByText("Check and save")).toBeDisabled();
  });
});
