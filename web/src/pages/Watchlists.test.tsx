import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { Watchlists } from "./Watchlists";

// Synthetic tickers, built from letters so no real symbol appears here.
const [A, B] = ["W", "X"].map((x) => [x, "Z", "Q", x].join(""));

const list = {
  name: "Mine",
  label: "2026-10-30 · eod",
  columns: ["ticker", "close", "in_scans", "exchange"],
  rows: [{ ticker: A, close: 10, in_scans: "ep_ah", exchange: "NASDAQ" }],
  tv_list: `NASDAQ:${A}`,
};

describe("Watchlists", () => {
  it("lists your list, adds with feedback and sets a price alert", async () => {
    const calls = mockApi({
      "GET /api/watchlists": { lists: ["Mine"], flags: [] },
      "GET /api/watchlists/Mine": list,
      "POST /api/watchlists/Mine/add": {
        kind: "warning",
        added: [B],
        already: [],
        unknown: ["QZQZ"],
        lines: [`✅ Added to **Mine**: ${B}`, "❌ Not found, not added: QZQZ"],
      },
      "GET /api/alerts": { directions: ["above", "below"], alerts: [], fired: [] },
      "POST /api/alerts": {
        directions: ["above", "below"],
        alerts: [{ alert_id: "1", ticker: A, level: 12.5, direction: "above", note: "" }],
        fired: [],
        message: `Alert set: ${A} above 12.50.`,
      },
      "GET /api/scan-watchlists": {
        bo_watch: { label: "BO-Watch", rows: [] },
        ep_watch: { label: "EP-Watch", rows: [] },
      },
    });
    render(<Watchlists />);
    expect(await screen.findByLabelText("Watchlist Mine")).toHaveTextContent(A);
    expect(screen.getByText(/Market data from/)).toBeInTheDocument();
    expect(screen.getByText(/EP-Watch and BO-Watch fill up/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Add tickers"), { target: { value: `${B} QZQZ` } });
    fireEvent.click(screen.getByText("Add to list"));
    const msg = await screen.findByText(/Not found, not added/);
    expect(msg.closest(".msg")).toHaveClass("warning");
    expect(screen.getByText("Mine", { selector: "b" })).toBeInTheDocument();
    const add = calls.find((c) => c.url === "/api/watchlists/Mine/add")!;
    expect(add.body).toEqual({ text: `${B} QZQZ`, export_text: "", note: "" });

    fireEvent.change(screen.getByLabelText("Ticker"), { target: { value: A } });
    fireEvent.change(screen.getByLabelText("Price"), { target: { value: "12.5" } });
    fireEvent.click(screen.getByText("Add alert"));
    expect(await screen.findByText(`Alert set: ${A} above 12.50.`)).toBeInTheDocument();
    expect(screen.getByLabelText("Your alerts")).toHaveTextContent("12.50");
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/alerts")).toBe(true));
  });

  it("adds to a new list under the name you typed, even if the lists load late", async () => {
    let release: () => void = () => {};
    const late = new Promise<void>((r) => (release = r));
    const calls = mockApi({
      "GET /api/watchlists": { lists: ["Mine"], flags: [] },
      "GET /api/watchlists/": list,
      "POST /api/watchlists/": { kind: "success", added: [A], already: [], unknown: [], lines: ["ok"] },
      "GET /api/alerts": { directions: ["above", "below"], alerts: [], fired: [] },
      "GET /api/scan-watchlists": {},
    });
    const real = globalThis.fetch;
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url === "/api/watchlists") await late; // the lists answer after you picked
      return real(url, init);
    });
    render(<Watchlists />);
    fireEvent.change(screen.getByLabelText("List"), { target: { value: "＋ New list" } });
    fireEvent.change(screen.getByLabelText("New list name"), { target: { value: "Other" } });
    release();
    await waitFor(() => expect(calls.some((c) => c.url === "/api/watchlists")).toBe(true));
    fireEvent.change(screen.getByLabelText("Add tickers"), { target: { value: A } });
    fireEvent.click(screen.getByText("Add to list"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/watchlists/Other/add")).toBe(true));
  });
});
