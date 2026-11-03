import { render, screen } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { Positions } from "./Positions";

const A = ["W", "Z", "Q", "W"].join(""); // synthetic

describe("Positions", () => {
  it("shows a card per open position with R, P&L, the stop and the plan", async () => {
    mockApi({
      "GET /api/positions": {
        source: "the newest daily close in the data repo (not live)",
        totals: { positions: 1, open_pnl: 200, at_risk_usd: 300, at_risk_pct: 0.3 },
        cards: [
          {
            ticker: A, setup: "ep_day", direction: "long", shares: 100, entry_date: "2026-10-01",
            entry: 10, price: 12, move_pct: 20, open_r: 2, pnl: 200, to_stop_pct: 25, stop: 9,
            facts: ["Plan: sell at the close after 21 sessions · day 3 of 21", "⚠️ day 21/21: past the plan's exit day"],
          },
        ],
        caption: "Exits are the plan's facts, not advice.",
      },
    });
    render(<Positions />);
    const card = await screen.findByLabelText(`${A} position`);
    expect(card).toHaveTextContent("+2.00R");
    expect(card).toHaveTextContent("$200");
    expect(card).toHaveTextContent("25.0%");
    expect(card).toHaveTextContent("stop 9.00");
    expect(card).toHaveTextContent("day 3 of 21");
    expect(screen.getByText(/not live/)).toBeInTheDocument();
  });

  it("says so when there are none", async () => {
    mockApi({
      "GET /api/positions": {
        source: null,
        totals: { positions: 0, open_pnl: 0, at_risk_usd: 0, at_risk_pct: null },
        cards: [],
      },
    });
    render(<Positions />);
    expect(await screen.findByText(/No open positions/)).toBeInTheDocument();
  });
});
