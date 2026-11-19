// Eight places (UX rounds 1-3, 18 Nov 2026): Today, Chart, Watchlists, Screener, Market, Journal, then
// Practice and Lab under "More". Hash
// routes keep working on a static server and keep a push link's query string (`?push=am&t=A,B`)
// for Today. The Chart takes the active stock and list in its address: `#/chart?s=TICKER&list=ID`.
// The old addresses (the twelve pages, and Stocks) still open the right place and tab, so
// bookmarks and older links keep working.

export type Place = "today" | "chart" | "watchlists" | "screener" | "market" | "journal" | "practice" | "lab";

export const PLACES: { id: Place; label: string; icon: string; question: string; short?: string }[] = [
  { id: "today", label: "Today", icon: "today", question: "What do I do today?" },
  { id: "chart", label: "Chart", icon: "chart", question: "One stock, with its list beside it" },
  { id: "watchlists", label: "Watchlists", short: "Lists", icon: "star", question: "Your lists, the scans' watch lists and alerts" },
  { id: "screener", label: "Screener", icon: "stocks", question: "Scan hits and screens: find stocks" },
  { id: "market", label: "Market", icon: "market", question: "How is the market?" },
  { id: "journal", label: "Journal", icon: "journal", question: "My trades and notes" },
  { id: "practice", label: "Practice", icon: "draw", question: "Replay past signals and test your calls" },
  { id: "lab", label: "Lab", icon: "lab", question: "Research and the system" },
];

/** The places in the top bar; Practice and Lab are in its More menu. */
export const MAIN_PLACES: Place[] = ["today", "chart", "watchlists", "screener", "market", "journal"];

/** The places on the phone's bottom bar; the rest are in More. */
export const PHONE_TABS: Place[] = ["today", "chart", "watchlists", "screener"];

export const TABS: Record<Place, readonly (readonly [string, string])[]> = {
  today: [],
  practice: [],
  chart: [],
  watchlists: [],
  screener: [
    ["hits", "Scan hits"],
    ["screen", "Screener"],
  ],
  market: [
    ["overview", "Overview"],
    ["heat", "Heat & setups"],
    ["sectors", "Sectors"],
    ["breadth", "Breadth"],
    ["ibd", "IBD"],
  ],
  journal: [
    ["trades", "Trades"],
    ["positions", "Positions"],
    ["plans", "Plans"],
    ["notes", "Notes"],
    ["live", "Live results"],
  ],
  lab: [
    ["research", "Research"],
    ["runs", "Runs"],
    ["scans", "Scans"],
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
  chart: ["chart", ""],
  positions: ["journal", "positions"],
  live: ["journal", "live"],
  research: ["lab", "research"],
  scans: ["lab", "scans"],
  health: ["lab", "health"],
  guide: ["lab", "guide"],
};

/** A Screener source (`list:Name`, `scan:id`) as the Chart's list id (`wl:Name`, `scan:id`). */
export function listOfSource(src: string | null | undefined): string | undefined {
  if (!src) return undefined;
  if (src.startsWith("list:")) return `wl:${src.slice(5)}`;
  if (src.startsWith("scan:")) return src;
  return undefined;
}

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const params = new URLSearchParams(query);
  const [head = "", sub = ""] = path.split("/");
  // Stocks was the one place for screens and charts: a stock in its address is the Chart now
  if (head === "stocks") {
    const t = params.get("t");
    if (!t) return { place: "screener", tab: "", params };
    const next = new URLSearchParams({ s: t.toUpperCase() });
    const list = listOfSource(params.get("src"));
    if (list) next.set("list", list);
    return { place: "chart", tab: "", params: next };
  }
  if (head in LEGACY) {
    const [place, tab] = LEGACY[head];
    if (place === "chart" && params.has("t") && !params.has("s")) {
      params.set("s", params.get("t")!.toUpperCase());
      params.delete("t");
    }
    return { place, tab, params };
  }
  const place = (PLACES.some((p) => p.id === head) ? head : "today") as Place;
  const tabs = TABS[place];
  const tab = tabs.some(([id]) => id === sub) ? sub : (tabs[0]?.[0] ?? "");
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

/** A stock on the Chart, with the list it came from when it has one. */
export const stockLink = (ticker: string, list?: string) =>
  hrefFor("chart", "", list ? { s: ticker, list } : { s: ticker });
