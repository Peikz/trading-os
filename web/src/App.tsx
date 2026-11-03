// Trading OS: five places with tabs inside (design review 4 Nov 2026). Today ("What do I do
// today?"), Stocks (find and study a stock), Market, Journal and Lab; every one of the twelve
// earlier pages lives in one of them. The top bar has the market in one word, search (Ctrl+K),
// settings and a status dot; on a phone the places move to a bottom tab bar. Pull latest and
// Save & push run by themselves (useSync), with the buttons kept in Settings.
import { useEffect, useState } from "react";
import { Journal } from "./pages/Journal";
import { Guide } from "./pages/Guide";
import { Market } from "./pages/Market";
import { Research } from "./pages/Research";
import { Scans } from "./pages/Scans";
import { SystemHealth } from "./pages/SystemHealth";
import { Stocks } from "./places/Stocks";
import { Today } from "./places/Today";
import { hrefFor, parseHash, PLACES, type Route, TABS } from "./routes";
import { CommandPalette } from "./shell/CommandPalette";
import { TopBar } from "./shell/TopBar";
import { useSync } from "./shell/useSync";
import { Icon } from "./ui/Icon";

function PlaceView({ route }: { route: Route }) {
  const { place, tab, params } = route;
  if (place === "today") return <Today />;
  if (place === "stocks") return <Stocks params={params} />;
  const meta = PLACES.find((p) => p.id === place)!;
  return (
    <div>
      <div className="place-head">
        <h1>{meta.label}</h1>
        <span className="muted">{meta.question}</span>
      </div>
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
      {place === "lab" && tab === "scans" && <Scans />}
      {place === "lab" && tab === "health" && <SystemHealth />}
      {place === "lab" && tab === "guide" && <Guide />}
    </div>
  );
}

export function App() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  const [palette, setPalette] = useState(false);
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
        setPalette((p) => !p);
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
      <TopBar place={route.place} sync={sync} onSearch={() => setPalette(true)} />
      <main className="place" key={version}>
        <PlaceView route={route} />
      </main>
      <nav className="tabbar" aria-label="Places (phone)">
        {PLACES.map((p) => (
          <a key={p.id} href={hrefFor(p.id)} aria-current={p.id === route.place ? "page" : undefined}>
            <Icon name={p.icon} size={22} />
            {p.label}
          </a>
        ))}
      </nav>
      {palette && <CommandPalette onClose={() => setPalette(false)} onPull={sync.pullNow} onPush={sync.pushNow} />}
    </div>
  );
}
