import { matchSymbols, type Symbol as Sym } from "./symbols";
import { readPref, writePref } from "./prefs";

const list: Sym[] = [
  { ticker: "WZQW", name: "Wizard Holdings" },
  { ticker: "WZQ", name: "Zeta Corp" },
  { ticker: "XQZX", name: "Wizard Works Inc." },
  { ticker: "VZQV", name: "Quartz Co" },
];

describe("matchSymbols", () => {
  it("puts tickers that start with the text first, then company names that contain it", () => {
    expect(matchSymbols(list, "wzq").map((s) => s.ticker)).toEqual(["WZQ", "WZQW"]);
    expect(matchSymbols(list, "wiz").map((s) => s.ticker)).toEqual(["WZQW", "XQZX"]);
  });
  it("puts an exact ticker first and finds nothing for unknown text", () => {
    expect(matchSymbols(list, "$wzq")[0].ticker).toBe("WZQ");
    expect(matchSymbols(list, "nothing here")).toEqual([]);
    expect(matchSymbols(list, "  ")).toEqual([]);
  });
  it("shows at most the asked number of rows", () => {
    const many = Array.from({ length: 50 }, (_, i) => ({ ticker: `Q${i}`, name: "" }));
    expect(matchSymbols(many, "q")).toHaveLength(20);
    expect(matchSymbols(many, "q", 5)).toHaveLength(5);
  });
});

describe("prefs", () => {
  it("remembers a choice and falls back when storage fails", () => {
    writePref("test-choice", { a: 1 });
    expect(readPref("test-choice", null)).toEqual({ a: 1 });
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readPref("test-choice", "fallback")).toBe("fallback");
    spy.mockRestore();
  });
});
