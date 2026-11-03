// Trading OS: Today (the candidate board) and the Screener. Hash routes (#/today, #/screener)
// keep a push link's query string (?t=A,B) working on a static file server.
import { useEffect, useState } from "react";
import { Screener } from "./pages/Screener";
import { Today } from "./pages/Today";

const PAGES = { today: "Today", screener: "Screener" } as const;
type Page = keyof typeof PAGES;

function current(): Page {
  const h = window.location.hash.replace(/^#\/?/, "");
  return h in PAGES ? (h as Page) : "today";
}

export function App() {
  const [page, setPage] = useState<Page>(current);
  useEffect(() => {
    const on = () => setPage(current());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return (
    <>
      <header className="top">
        <b>Trading OS</b>
        <nav>
          {(Object.keys(PAGES) as Page[]).map((p) => (
            <a key={p} href={`#/${p}`} className={p === page ? "on" : ""}>
              {PAGES[p]}
            </a>
          ))}
        </nav>
      </header>
      <main>{page === "today" ? <Today /> : <Screener />}</main>
    </>
  );
}
