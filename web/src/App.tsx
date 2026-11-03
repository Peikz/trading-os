// Trading OS: the pages in the order of the trading day, as in the Streamlit sidebar (before
// the open: Today, Watchlists, Screener; live: Positions; after the close: Journal). Hash routes
// (#/today, #/journal...) keep a push link's query string (?t=A,B) working on a static server.
import { useEffect, useState } from "react";
import { Chart } from "./pages/Chart";
import { Journal } from "./pages/Journal";
import { Positions } from "./pages/Positions";
import { Screener } from "./pages/Screener";
import { Today } from "./pages/Today";
import { Watchlists } from "./pages/Watchlists";

const PAGES = {
  today: ["☀️ Today", Today],
  watchlists: ["☀️ Watchlists", Watchlists],
  screener: ["☀️ Screener", Screener],
  positions: ["⚡ Positions", Positions],
  chart: ["⚡ Chart", Chart],
  journal: ["🌙 Journal", Journal],
} as const;
type Page = keyof typeof PAGES;

function current(): Page {
  const h = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return h in PAGES ? (h as Page) : "today";
}

export function App() {
  const [page, setPage] = useState<Page>(current);
  useEffect(() => {
    const on = () => setPage(current());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const Shown = PAGES[page][1];
  return (
    <>
      <header className="top">
        <b>Trading OS</b>
        <nav>
          {(Object.keys(PAGES) as Page[]).map((p) => (
            <a key={p} href={`#/${p}`} className={p === page ? "on" : ""}>
              {PAGES[p][0]}
            </a>
          ))}
        </nav>
      </header>
      <main>
        <Shown />
      </main>
    </>
  );
}
