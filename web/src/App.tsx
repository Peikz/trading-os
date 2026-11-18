// Trading OS: six places with tabs inside where they have them. Today ("What do I do today?"),
// Chart (one stock with its list beside it), Screener, Market, Journal and Lab; every one of the
// twelve earlier pages lives in one of them. The top bar has the places, the market in one word,
// search (Ctrl+K, "/", or just type a ticker), settings and a status dot; on a phone the places
// move to a bottom tab bar (Today, Chart, Screener, Market, More). Pull latest and Save & push
// run by themselves (useSync), with the buttons kept in Settings.
import { useEffect, useState } from "react";
import { Journal } from "./pages/Journal";
import { Guide } from "./pages/Guide";
import { Market } from "./pages/Market";
import { Research } from "./pages/Research";
import { Runs } from "./pages/Runs";
import { SystemHealth } from "./pages/SystemHealth";
import { ChartWorkspace } from "./places/ChartWorkspace";
import { Stocks as Screener } from "./places/Stocks";
import { Today } from "./places/Today";
import { hrefFor, parseHash, PLACES, type Place, type Route, TABS } from "./routes";
import { CommandPalette } from "./shell/CommandPalette";
import { MobileNav } from "./shell/MobileNav";
import { TopBar } from "./shell/TopBar";
import { useSync } from "./shell/useSync";
import { typing } from "./ui/kit";

// Letters a place uses itself, so typing them does not open the search
const OWN_KEYS: Partial<Record<Place, string>> = { today: "wn", chart: "jk" };

function PlaceView({ route }: { route: Route }) {
  const { place, tab, params } = route;
  if (place === "today") return <Today />;
  if (place === "chart") return <ChartWorkspace params={params} />;
  if (place === "screener") return <Screener params={params} />;
  const meta = PLACES.find((p) => p.id === place)!;
  return (
    <div>
      <h1 className="sr-only">{meta.label}</h1>
      <div className="tabs place-tabs" role="tablist" aria-label={`${meta.label} tabs`}>
        {TABS[place].map(([id, text]) => (
          <a
            key={id}
            role="tab"
            aria-selected={id === tab}
            href={hrefFor(place, id)}
            className={`tab-link${id === tab ? " on" : ""}`}
          >
            {text}
          </a>
        ))}
      </div>
      {place === "market" && <Market tab={tab} />}
      {place === "journal" && <Journal tab={tab} />}
      {place === "lab" && tab === "research" && <Research />}
      {place === "lab" && tab === "runs" && <Runs />}
      {place === "lab" && tab === "health" && <SystemHealth />}
      {place === "lab" && tab === "guide" && <Guide />}
    </div>
  );
}

export function App() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  const [palette, setPalette] = useState<string | null>(null); // the search's first letters; null: closed
  const [version, setVersion] = useState(0);
  const sync = useSync();

  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => (p === null ? "" : null));
        return;
      }
      if (typing(e) || e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
      if (document.querySelector(".palette-back")) return;
      const own = OWN_KEYS[parseHash(window.location.hash).place] ?? "";
      if (e.key === "/") {
        e.preventDefault();
        setPalette("");
      } else if (/^[a-z]$/i.test(e.key) && !own.includes(e.key.toLowerCase())) {
        e.preventDefault();
        setPalette(e.key.toUpperCase());
      }
    };
    const refresh = () => setVersion((v) => v + 1);
    window.addEventListener("keydown", onKey);
    window.addEventListener("trading-os:refresh", refresh);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("trading-os:refresh", refresh);
    };
  }, []);
  useEffect(() => {
    const label = PLACES.find((p) => p.id === route.place)?.label ?? "Today";
    document.title = `${label} · Trading OS`;
  }, [route.place]);

  return (
    <div className="shell">
      <TopBar place={route.place} sync={sync} onSearch={() => setPalette("")} />
      <main className={`place${route.place === "chart" ? " wide" : ""}`} key={version}>
        <PlaceView route={route} />
      </main>
      <MobileNav place={route.place} />
      {palette !== null && (
        <CommandPalette
          initial={palette}
          onClose={() => setPalette(null)}
          onPull={sync.pullNow}
          onPush={sync.pushNow}
        />
      )}
    </div>
  );
}
