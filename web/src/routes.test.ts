import { hrefFor, parseHash, stockLink } from "./routes";

describe("routes", () => {
  it("reads the seven places and their tabs, the first tab by default", () => {
    expect(parseHash("")).toMatchObject({ place: "today", tab: "" });
    expect(parseHash("#/market/sectors")).toMatchObject({ place: "market", tab: "sectors" });
    expect(parseHash("#/journal")).toMatchObject({ place: "journal", tab: "trades" });
    expect(parseHash("#/practice")).toMatchObject({ place: "practice", tab: "" });
    expect(parseHash("#/lab/nope")).toMatchObject({ place: "lab", tab: "research" });
    expect(parseHash("#/nowhere")).toMatchObject({ place: "today" });
  });

  it("sends the twelve old page addresses to their place and tab", () => {
    const chart = parseHash("#/chart?t=WZQW");
    expect(chart.place).toBe("chart");
    expect(chart.params.get("s")).toBe("WZQW");
    expect(parseHash("#/watchlists")).toMatchObject({ place: "watchlists" });
    expect(parseHash("#/screener")).toMatchObject({ place: "screener", tab: "hits" });
    expect(parseHash("#/screener/screen")).toMatchObject({ place: "screener", tab: "screen" });
    // Stocks, the place before the Chart and the Screener were split
    expect(parseHash("#/stocks?src=all")).toMatchObject({ place: "screener" });
    const stock = parseHash("#/stocks?src=list:Mine&t=wzqw");
    expect(stock.place).toBe("chart");
    expect(stock.params.get("s")).toBe("WZQW");
    expect(stock.params.get("list")).toBe("wl:Mine");
    expect(parseHash("#/positions")).toMatchObject({ place: "journal", tab: "positions" });
    expect(parseHash("#/live")).toMatchObject({ place: "journal", tab: "live" });
    expect(parseHash("#/health")).toMatchObject({ place: "lab", tab: "health" });
    expect(parseHash("#/scans")).toMatchObject({ place: "lab", tab: "scans" });
    expect(parseHash("#/lab/scans")).toMatchObject({ place: "lab", tab: "scans" });
    expect(parseHash("#/guide")).toMatchObject({ place: "lab", tab: "guide" });
    expect(parseHash("#/research")).toMatchObject({ place: "lab", tab: "research" });
    expect(parseHash("#/market")).toMatchObject({ place: "market", tab: "overview" });
    expect(parseHash("#/journal")).toMatchObject({ place: "journal", tab: "trades" });
  });

  it("writes links", () => {
    expect(hrefFor("market", "ibd")).toBe("#/market/ibd");
    expect(hrefFor("screener", "screen", { sector: "A,B" })).toBe("#/screener/screen?sector=A%2CB");
    expect(stockLink("WZQW")).toBe("#/chart?s=WZQW");
    expect(stockLink("WZQW", "wl:Mine")).toBe("#/chart?s=WZQW&list=wl%3AMine");
  });
});
