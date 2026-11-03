import { hrefFor, parseHash, stockLink } from "./routes";

describe("routes", () => {
  it("reads the five places and their tabs, the first tab by default", () => {
    expect(parseHash("")).toMatchObject({ place: "today", tab: "" });
    expect(parseHash("#/market/sectors")).toMatchObject({ place: "market", tab: "sectors" });
    expect(parseHash("#/journal")).toMatchObject({ place: "journal", tab: "positions" });
    expect(parseHash("#/lab/nope")).toMatchObject({ place: "lab", tab: "research" });
    expect(parseHash("#/nowhere")).toMatchObject({ place: "today" });
  });

  it("sends the twelve old page addresses to their place and tab", () => {
    const chart = parseHash("#/chart?t=WZQW");
    expect(chart.place).toBe("stocks");
    expect(chart.params.get("t")).toBe("WZQW");
    expect(parseHash("#/watchlists").params.get("src")).toBe("lists");
    expect(parseHash("#/screener").params.get("src")).toBe("all");
    expect(parseHash("#/positions")).toMatchObject({ place: "journal", tab: "positions" });
    expect(parseHash("#/live")).toMatchObject({ place: "journal", tab: "live" });
    expect(parseHash("#/health")).toMatchObject({ place: "lab", tab: "health" });
    expect(parseHash("#/scans")).toMatchObject({ place: "lab", tab: "scans" });
    expect(parseHash("#/guide")).toMatchObject({ place: "lab", tab: "guide" });
    expect(parseHash("#/research")).toMatchObject({ place: "lab", tab: "research" });
    expect(parseHash("#/market")).toMatchObject({ place: "market", tab: "overview" });
    expect(parseHash("#/journal")).toMatchObject({ place: "journal", tab: "positions" });
  });

  it("writes links", () => {
    expect(hrefFor("market", "ibd")).toBe("#/market/ibd");
    expect(hrefFor("stocks", "", { src: "list:My list" })).toBe("#/stocks?src=list%3AMy+list");
    expect(stockLink("WZQW")).toBe("#/stocks?t=WZQW");
  });
});
