import { plain, stripIcons } from "./plain";

describe("plain words", () => {
  it("names a label in plain words and keeps the term in the tooltip", () => {
    expect(plain("ADR")).toEqual({ text: "Daily range", title: "ADR %: average daily range over 20 days" });
    expect(plain("Mkt cap")).toEqual({ text: "Market cap", title: "Mkt cap" });
    expect(plain("open_pnl")).toEqual({ text: "Open P&L", title: "open_pnl" });
    expect(plain("some_new_column")).toEqual({ text: "Some new column", title: "some_new_column" });
    expect(plain("Ticker")).toEqual({ text: "Ticker" });
  });

  it("drops the icons the package puts in front of a line", () => {
    expect(stripIcons("🟢 GREEN")).toBe("GREEN");
    expect(stripIcons("⚠️ Earnings tomorrow")).toBe("Earnings tomorrow");
    expect(stripIcons("Buy 10.00")).toBe("Buy 10.00");
  });
});
