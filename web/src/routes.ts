// Five places with tabs inside (design review 4 Nov 2026). Hash routes keep working on a static
// server and keep a push link's query string (`?push=am&t=A,B`) for Today. The twelve old page
// addresses still open the right place and tab, so bookmarks and older links keep working.

export type Place = "today" | "stocks" | "market" | "journal" | "lab";

export const PLACES: { id: Place; label: string; icon: string; question: string }[] = [
  { id: "today", label: "Today", icon: "today", question: "What do I do today?" },
  { id: "stocks", label: "Stocks", icon: "stocks", question: "Find and study a stock" },
  { id: "market", label: "Market", icon: "market", question: "How is the market?" },
  { id: "journal", label: "Journal", icon: "journal", question: "My trades and notes" },
  { id: "lab", label: "Lab", icon: "lab", question: "Research and the system" },
];

export const TABS: Record<Place, readonly (readonly [string, string])[]> = {
  today: [],
  stocks: [],
  market: [
    ["overview", "Overview"],
    ["heat", "Heat & setups"],
    ["sectors", "Sectors"],
    ["breadth", "Breadth"],
    ["ibd", "IBD"],
  ],
  journal: [
    ["positions", "Positions"],
    ["trades", "Trades"],
    ["plans", "Plans"],
    ["notes", "Notes"],
    ["live", "Live vs study"],
  ],
  lab: [
    ["research", "Research"],
    ["runs", "Runs"],
    ["health", "Health"],
    ["guide", "Guide"],
  ],
};

export interface Route {
  place: Place;
  tab: string;
  params: URLSearchParams;
}

// The old pages (12, before Nov 2026): place, tab, and how their query maps
const LEGACY: Record<string, [Place, string]> = {
  chart: ["stocks", ""],
  watchlists: ["stocks", ""],
  screener: ["stocks", ""],
  positions: ["journal", "positions"],
  live: ["journal", "live"],
  research: ["lab", "research"],
  scans: ["lab", "runs"],
  health: ["lab", "health"],
  guide: ["lab", "guide"],
};

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const params = new URLSearchParams(query);
  const [head = "", sub = ""] = path.split("/");
  if (head in LEGACY) {
    const [place, tab] = LEGACY[head];
    if (head === "watchlists" && !params.has("src")) params.set("src", "lists");
    if (head === "screener" && !params.has("src")) params.set("src", "all");
    return { place, tab, params };
  }
  const place = (PLACES.some((p) => p.id === head) ? head : "today") as Place;
  const tabs = TABS[place];
  const wanted = place === "lab" && sub === "scans" ? "runs" : sub; // Scans became Runs (4 Nov 2026)
  const tab = tabs.some(([id]) => id === wanted) ? wanted : (tabs[0]?.[0] ?? "");
  return { place, tab, params };
}

export function hrefFor(place: Place, tab = "", params?: Record<string, string> | URLSearchParams): string {
  const q = params instanceof URLSearchParams ? params : new URLSearchParams(params ?? {});
  const qs = q.toString();
  return `#/${place}${tab ? `/${tab}` : ""}${qs ? `?${qs}` : ""}`;
}

export function go(place: Place, tab = "", params?: Record<string, string>): void {
  window.location.hash = hrefFor(place, tab, params);
}

/** The Stocks place with one stock's full chart open. */
export const stockLink = (ticker: string, src?: string) =>
  hrefFor("stocks", "", src ? { src, t: ticker } : { t: ticker });
