// The top bar: logo, the five places, the market in one word, search (Ctrl+K), settings and a
// status dot that replaces checking System health. Facts only: the market word sums up the
// three things the push shows and nothing trades on it.
import { useEffect, useState } from "react";
import { api, type Market, type Status } from "../api";
import { deltaColour } from "../format";
import { hrefFor, PLACES, type Place } from "../routes";
import { Icon } from "../ui/Icon";
import { usePopover } from "../ui/kit";
import { ago, type Sync } from "./useSync";

export function TopBar({
  place,
  sync,
  onSearch,
}: {
  place: Place;
  sync: Sync;
  onSearch: () => void;
}) {
  return (
    <header className="top">
      <a className="logo" href={hrefFor("today")} aria-label="Trading OS, Today">
        <span className="logo-mark" aria-hidden="true">
          <Icon name="market" size={15} />
        </span>
        <span className="name">Trading OS</span>
      </a>
      <nav className="places seg" aria-label="Places">
        {PLACES.map((p) => (
          <a
            key={p.id}
            href={hrefFor(p.id)}
            aria-current={p.id === place ? "page" : undefined}
            className={`seg-link${p.id === place ? " on" : ""}`}
          >
            {p.label}
          </a>
        ))}
      </nav>
      <MarketPill />
      <span className="grow" />
      <div className="top-actions">
        {sync.fresh && (
          <button
            className="pill fresh"
            title="A pull brought new runs: show them"
            onClick={() => {
              sync.clearFresh();
              window.dispatchEvent(new Event("trading-os:refresh"));
            }}
          >
            <Icon name="refresh" size={16} />
            New data
          </button>
        )}
        <button className="search-btn" onClick={onSearch} aria-label="Search stocks, pages and tabs">
          <Icon name="search" size={16} />
          <span className="label">Search</span>
          <kbd>Ctrl K</kbd>
        </button>
        <SettingsMenu sync={sync} />
        <StatusDot sync={sync} />
      </div>
    </header>
  );
}

export function MarketPill() {
  const [market, setMarket] = useState<Market | null>(null);
  const [failed, setFailed] = useState(false);
  const { open, setOpen, ref } = usePopover();
  useEffect(() => {
    const load = () => api.market().then(setMarket, () => setFailed(true));
    load();
    window.addEventListener("trading-os:refresh", load);
    return () => window.removeEventListener("trading-os:refresh", load);
  }, []);
  const mood = market?.mood;
  const word = failed ? "Market unknown" : !market ? "Market…" : (mood?.word ?? "No market data");
  return (
    <div className="popover-wrap" ref={ref}>
      <button
        className="pill"
        aria-expanded={open}
        aria-label={`Market: ${word}. Show why`}
        onClick={() => setOpen(!open)}
      >
        <span className={`dot ${mood?.level ?? ""}`} aria-hidden="true" />
        <span className="word">{word}</span>
      </button>
      {open && (
        <div className="popover left" role="dialog" aria-label="Market">
          <h4>Why "{word.toLowerCase()}"</h4>
          {mood && mood.reasons.length > 0 ? (
            <ul className="reasons">
              {mood.reasons.map((r) => (
                <li key={r.text}>
                  <span className={`dot ${r.level}`} aria-hidden="true" />
                  <span>{r.text}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No market row yet: it comes with the first EOD run.</p>
          )}
          {mood && mood.quotes.length > 0 && (
            <div className="quotes">
              {mood.quotes.map((q) => (
                <div className="quote" key={q.label}>
                  <span>{q.label}</span>
                  <b className="num">{q.value}</b>{" "}
                  {q.delta && (
                    <small className="num" style={{ color: deltaColour(q.label, q.delta) }}>
                      {q.delta}
                    </small>
                  )}
                </div>
              ))}
            </div>
          )}
          <p className="muted hint">
            Healthy when all three are green, weak when two are red, cautious otherwise. A
            summary of facts, not a rule.
          </p>
          <a href={hrefFor("market", "overview")} onClick={() => setOpen(false)}>
            Open Market
          </a>
        </div>
      )}
    </div>
  );
}

function StatusDot({ sync }: { sync: Sync }) {
  const [status, setStatus] = useState<Status | null>(null);
  const { open, setOpen, ref } = usePopover();
  useEffect(() => {
    const load = () =>
      api.status().then(setStatus, (e: Error) =>
        setStatus({ level: "warn", text: `Status unknown (${e.message})`, details: [] }),
      );
    load();
    const every = setInterval(load, 5 * 60 * 1000);
    window.addEventListener("trading-os:refresh", load);
    return () => {
      clearInterval(every);
      window.removeEventListener("trading-os:refresh", load);
    };
  }, []);
  const syncFailed = (sync.pull && !sync.pull.ok) || (sync.push && !sync.push.ok);
  const level = status?.level === "error" ? "error" : syncFailed || status?.level === "warn" ? "warn" : status ? "ok" : "";
  const text = status?.text ?? "Checking…";
  return (
    <div className="popover-wrap" ref={ref}>
      <button
        className="ghost status-btn"
        aria-label={`System status: ${text}${syncFailed ? ", sync failed" : ""}`}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className={`dot ${level}`} aria-hidden="true" />
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="System status">
          <h4>System</h4>
          <p>
            <span className={`dot ${status?.level ?? ""}`} aria-hidden="true" /> {text}
          </p>
          {status && status.details.length > 0 && (
            <ul className="muted">
              {status.details.slice(0, 8).map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          )}
          <SyncLines sync={sync} />
          <a href={hrefFor("lab", "health")} onClick={() => setOpen(false)}>
            Open Health
          </a>
        </div>
      )}
    </div>
  );
}

function SyncLines({ sync }: { sync: Sync }) {
  return (
    <div className="settings-row" style={{ display: "block" }}>
      <div className="muted">
        Pull latest:{" "}
        {sync.busy === "pull" ? "running…" : sync.pull ? `${sync.pull.ok ? "done" : "failed"} ${ago(sync.pull.at)}` : "not yet"}
      </div>
      {sync.pull && !sync.pull.ok && <div className="error pre">{sync.pull.message}</div>}
      <div className="muted">
        Save & push:{" "}
        {sync.busy === "push"
          ? "running…"
          : sync.push
            ? `${sync.push.ok ? "done" : "failed"} ${ago(sync.push.at)}`
            : sync.unsaved
              ? "changes waiting"
              : "nothing to save yet"}
      </div>
      {sync.push && !sync.push.ok && <div className="error pre">{sync.push.message}</div>}
    </div>
  );
}

function SettingsMenu({ sync }: { sync: Sync }) {
  const { open, setOpen, ref } = usePopover();
  return (
    <div className="popover-wrap" ref={ref}>
      <button className="ghost icon-btn" aria-label="Settings" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name="gear" />
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Settings">
          <h4>Sync with the data repo</h4>
          <label className="check settings-row" style={{ justifyContent: "flex-start" }}>
            <input type="checkbox" checked={sync.auto} onChange={(e) => sync.setAuto(e.target.checked)} />
            Pull and save automatically
          </label>
          <SyncLines sync={sync} />
          <div className="row">
            <button disabled={sync.busy !== null} onClick={sync.pullNow} title="Fetch the newest runs from GitHub">
              <Icon name="refresh" size={16} />
              Pull latest
            </button>
            <button
              disabled={sync.busy !== null}
              onClick={sync.pushNow}
              title="Send your grades, notes, journal, watchlists, alerts, drawings and screens to the private data repo"
            >
              <Icon name="upload" size={16} />
              Save & push
            </button>
          </div>
          <h4 style={{ marginTop: 16 }}>Keys</h4>
          <p className="hotkeys">
            <kbd>Ctrl K</kbd> search · on Today <kbd>↑</kbd> <kbd>↓</kbd> flip, <kbd>W</kbd> watch,{" "}
            <kbd>N</kbd> note
          </p>
        </div>
      )}
    </div>
  );
}
