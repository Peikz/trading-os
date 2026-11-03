// Trading OS: the pages in the order of the trading day, as in the Streamlit sidebar: ☀️ before
// the open, ⚡ live, 🌙 after the close, 🔬 research and settings. Hash routes (#/today,
// #/chart?t=XXX...) keep a push link's query string (?t=A,B) working on a static server.
// Pull latest fetches the newest runs into the dashboard's data repo copy; Save & push sends
// your grades, notes, journal, watchlists, alerts and drawings to the private data repo.
import { useEffect, useState } from "react";
import { api } from "./api";
import { Chart } from "./pages/Chart";
import { Journal } from "./pages/Journal";
import { LiveResults } from "./pages/LiveResults";
import { Positions } from "./pages/Positions";
import { Research } from "./pages/Research";
import { Scans } from "./pages/Scans";
import { Screener } from "./pages/Screener";
import { SystemHealth } from "./pages/SystemHealth";
import { Today } from "./pages/Today";
import { Watchlists } from "./pages/Watchlists";

const PAGES = {
  today: ["☀️ Today", Today],
  watchlists: ["☀️ Watchlists", Watchlists],
  screener: ["☀️ Screener", Screener],
  positions: ["⚡ Positions", Positions],
  chart: ["⚡ Chart", Chart],
  scans: ["⚡ Scans", Scans],
  journal: ["🌙 Journal", Journal],
  live: ["🌙 Live results", LiveResults],
  research: ["🔬 Research", Research],
  health: ["🔬 System health", SystemHealth],
} as const;
type Page = keyof typeof PAGES;

export function current(hash: string): Page {
  const h = hash.replace(/^#\/?/, "").split("?")[0];
  return h in PAGES ? (h as Page) : "today";
}

export function App() {
  const [page, setPage] = useState<Page>(() => current(window.location.hash));
  const [sync, setSync] = useState<{ ok: boolean; message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const on = () => setPage(current(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const run = (call: () => Promise<{ ok: boolean; message: string }>) => {
    setBusy(true);
    call()
      .then(setSync, (e: Error) => setSync({ ok: false, message: e.message }))
      .finally(() => setBusy(false));
  };
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
        <div className="sync">
          <button disabled={busy} title="Fetch the newest runs from GitHub" onClick={() => run(api.pull)}>
            Pull latest
          </button>
          <button
            disabled={busy}
            title="Send your grades, notes, journal, watchlists, alerts and drawings to the private data repo"
            onClick={() => run(api.push)}
          >
            Save & push
          </button>
        </div>
      </header>
      {sync && (
        <p className={`sync-msg ${sync.ok ? "ok" : "error"}`} role="status">
          {sync.message}{" "}
          <button className="link" aria-label="Dismiss" onClick={() => setSync(null)}>
            ✕
          </button>
        </p>
      )}
      <main>
        <Shown />
      </main>
    </>
  );
}
