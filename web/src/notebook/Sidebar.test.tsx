// "Note on a stock" (26 Nov 2026): any stock gets a page from its ticker or name, so its first
// note can be written in the Journal. Synthetic tickers, built from letters.
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { NbIndex } from "../api";
import { resetSymbols } from "../shell/symbols";
import { mockApi } from "../test/mockApi";
import { Sidebar } from "./Sidebar";

const [A, B] = ["W", "X"].map((x) => [x, "Z", "Q", x].join(""));

const index = {
  today: "2026-11-26",
  daily: [],
  trades: [],
  stocks: [],
  pages: [],
} as unknown as NbIndex;

function sidebar(query = "") {
  return render(
    <Sidebar
      index={index}
      entries={[]}
      selected={null}
      query={query}
      onQuery={() => {}}
      onNewPage={() => {}}
      todayHasNote={false}
    />,
  );
}

beforeEach(() => {
  resetSymbols();
  window.location.hash = "";
  window.localStorage.clear();
  mockApi({ "GET /api/symbols": { asof: "x", symbols: [[A, "Wizard Corp"], [B, "Other Inc"]] } });
});

describe("Note on a stock", () => {
  it("suggests stocks by ticker or name and links to the stock's page", async () => {
    sidebar();
    const box = screen.getByLabelText("Note on a stock");
    fireEvent.change(box, { target: { value: "wizard" } });
    const list = await screen.findByLabelText("Stocks to write a note on");
    expect(within(list).getByRole("link", { name: new RegExp(A) })).toHaveAttribute(
      "href",
      `#/journal/notes?p=stock%3A${A}`,
    );
    expect(screen.getByText(/No stock notes yet/)).toBeInTheDocument();
  });

  it("Enter opens the first match, or a typed ticker the universe doesn't know", async () => {
    sidebar();
    const box = screen.getByLabelText("Note on a stock");
    fireEvent.change(box, { target: { value: B.toLowerCase() } });
    await screen.findByLabelText("Stocks to write a note on");
    fireEvent.keyDown(box, { key: "Enter" });
    expect(window.location.hash).toBe(`#/journal/notes?p=stock%3A${B}`);
    fireEvent.change(box, { target: { value: "$QQZZ" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(window.location.hash).toBe("#/journal/notes?p=stock%3AQQZZ");
  });

  it("a ticker typed in the search offers that stock's page", async () => {
    sidebar(A.toLowerCase());
    const results = screen.getByLabelText("Search results");
    const link = await within(results).findByRole("link", { name: new RegExp(`Note on \\$${A}`) });
    expect(link).toHaveAttribute("href", `#/journal/notes?p=stock%3A${A}`);
  });
});
