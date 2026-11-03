// Watchlists: your own lists (add by typing or a TradingView export, each ticker checked, with
// the newest close's numbers and the scans it hit), your price alerts, and the scans' EP-Watch
// and BO-Watch. Saved in the data repo; Save & push (Streamlit, for now) sends them to GitHub.
import { useCallback, useEffect, useState } from "react";
import { api, type Alerts, type ScanWatchlists, type WatchAdded, type WatchList } from "../api";
import { Marked, Table } from "../components/Table";
import { download, readText } from "../format";

const NEW = "＋ New list";

export function Watchlists() {
  const [lists, setLists] = useState<string[]>([]);
  // null until the lists load (then the first list, or a new one); never overrides your pick
  const [choice, setChoice] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [list, setList] = useState<WatchList | null>(null);
  const [typed, setTyped] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [added, setAdded] = useState<WatchAdded | null>(null);
  const [gone, setGone] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const name = choice === NEW ? newName : (choice ?? "");

  const loadLists = useCallback(
    (pick?: string) =>
      api.watchlists().then((w) => {
        setLists(w.lists);
        setChoice((c) => pick ?? c ?? (w.lists.length ? w.lists[0] : NEW));
      }, (e: Error) => setError(e.message)),
    [],
  );
  useEffect(() => {
    loadLists();
  }, [loadLists]);
  useEffect(() => {
    setGone([]);
    if (choice === null || choice === NEW) return setList(null);
    api.watchlist(choice).then(setList, (e: Error) => setError(e.message));
  }, [choice]);

  const add = async () => {
    const exportText = file ? await readText(file) : "";
    try {
      const out = await api.addToWatchlist(name, typed, exportText, note);
      setAdded(out);
      if (out.added.length) {
        setTyped("");
        setFile(null);
        await loadLists(name.trim());
        if (choice && name.trim() === choice) setList(await api.watchlist(choice));
      }
    } catch (e) {
      setAdded({ kind: "error", added: [], already: [], unknown: [], lines: [(e as Error).message] });
    }
  };
  const remove = () =>
    api.removeFromWatchlist(choice ?? "", gone).then((l) => {
      setList(l);
      setGone([]);
      if (!l.rows.length) loadLists();
    }, (e: Error) => setError(e.message));

  return (
    <div>
      <h2>Watchlists</h2>
      {error && <p className="error">{error}</p>}
      <h3>My watchlists</h3>
      <div className="row">
        <select aria-label="List" value={choice ?? NEW} onChange={(e) => setChoice(e.target.value)}>
          {lists.map((l) => (
            <option key={l}>{l}</option>
          ))}
          <option>{NEW}</option>
        </select>
        {choice === NEW && (
          <input
            aria-label="New list name"
            placeholder="New list name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
        )}
      </div>
      <div className="row">
        <input
          aria-label="Add tickers"
          placeholder="Add tickers (comma or space separated)"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
        />
        <input
          aria-label="Note (optional)"
          placeholder="Note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <label>
          …or a TradingView export (.txt){" "}
          <input
            aria-label="TradingView export"
            type="file"
            accept=".txt"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <button onClick={add}>Add to list</button>
      </div>
      {added && (
        <div className={`msg ${added.kind}`} role="status">
          {added.lines.map((l) => (
            <div key={l}>
              <Marked text={l} />
            </div>
          ))}
        </div>
      )}
      {list && list.rows.length === 0 && <p className="muted">No tickers in this list yet.</p>}
      {list && list.rows.length > 0 && (
        <>
          {list.label && (
            <p className="muted">
              Market data from {list.label}. in_scans = the scans it hit that run.
            </p>
          )}
          <Table
            label={`Watchlist ${list.name}`}
            columns={list.columns.filter((c) => c !== "exchange")}
            rows={list.rows}
          />
          <div className="row">
            <button
              title="TradingView: Watchlist menu → Import list"
              onClick={() => download(`${list.name}.txt`, list.tv_list)}
            >
              TradingView list (.txt)
            </button>
            <select
              aria-label="Remove from the list"
              multiple
              value={gone}
              onChange={(e) => setGone(Array.from(e.target.selectedOptions, (o) => o.value))}
            >
              {list.rows.map((r) => (
                <option key={String(r.ticker)}>{String(r.ticker)}</option>
              ))}
            </select>
            <button onClick={remove} disabled={!gone.length}>
              Remove
            </button>
          </div>
        </>
      )}
      <p className="muted">Saved in the data repo; Save & push sends them to GitHub.</p>
      <PriceAlerts />
      <ScanLists />
    </div>
  );
}

function PriceAlerts() {
  const [data, setData] = useState<Alerts | null>(null);
  const [ticker, setTicker] = useState("");
  const [level, setLevel] = useState("");
  const [side, setSide] = useState("above");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    api.alerts().then(setData, (e: Error) => setMessage(`❌ ${e.message}`));
  }, []);

  const add = () =>
    api.addAlert(ticker, Number(level), side, note).then(
      (a) => {
        setData(a);
        setMessage(a.message ?? null);
        setTicker("");
        setLevel("");
        setNote("");
      },
      (e: Error) => setMessage(`❌ ${e.message}`),
    );

  return (
    <section>
      <h3>Price alerts</h3>
      <p className="muted">
        The alert watcher checks every minute of the New York session and pushes once when a
        price is hit: your alerts below, last close's BO-Watch and MA-surf pivots, and your open
        positions' stops. Your alerts end after they fire.
      </p>
      <div className="row">
        <input aria-label="Ticker" placeholder="Ticker" value={ticker} onChange={(e) => setTicker(e.target.value)} />
        <input
          aria-label="Price"
          type="number"
          step="0.01"
          min="0"
          placeholder="Price"
          value={level}
          onChange={(e) => setLevel(e.target.value)}
        />
        <select aria-label="When it trades" value={side} onChange={(e) => setSide(e.target.value)}>
          {(data?.directions ?? ["above", "below"]).map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
        <input aria-label="Note (in the push)" placeholder="Note (in the push)" value={note} onChange={(e) => setNote(e.target.value)} />
        <button onClick={add}>Add alert</button>
      </div>
      {message && <p className={message.startsWith("❌") ? "error" : "ok"}>{message}</p>}
      {data && data.alerts.length === 0 && <p className="muted">No alerts of your own yet.</p>}
      {data && data.alerts.length > 0 && (
        <Table
          label="Your alerts"
          columns={["ticker", "direction", "level", "note", ""]}
          rows={data.alerts.map((a) => ({ ...a }))}
          render={(c, r) =>
            c === "" ? (
              <button
                className="link"
                aria-label={`Remove ${r.ticker} ${r.direction} ${r.level}`}
                onClick={() => api.removeAlert(String(r.alert_id)).then(setData)}
              >
                ✕
              </button>
            ) : undefined
          }
        />
      )}
      {data && data.fired.length > 0 && (
        <>
          <b>Fired today ({data.fired.length})</b>
          <Table
            label="Fired today"
            columns={["fired_ts", "kind", "ticker", "level", "price", "note"]}
            rows={data.fired}
          />
        </>
      )}
    </section>
  );
}

function ScanLists() {
  const [all, setAll] = useState(false);
  const [data, setData] = useState<ScanWatchlists | null>(null);
  useEffect(() => {
    api.scanWatchlists(all).then(setData, () => setData(null));
  }, [all]);
  const empty = data && Object.values(data).every((w) => w.rows.length === 0);
  return (
    <section>
      <h3>Scan watchlists</h3>
      <label className="check">
        <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
        Include triggered / expired
      </label>
      {empty && <p className="muted">EP-Watch and BO-Watch fill up as EP and breakout alerts come in.</p>}
      {data &&
        !empty &&
        Object.entries(data).map(([id, w]) => (
          <div key={id}>
            <b>
              {w.label} ({w.rows.length})
            </b>
            <Table
              label={w.label}
              columns={["ticker", "status", "added_date", "status_date", "reason"]}
              rows={w.rows}
            />
          </div>
        ))}
    </section>
  );
}
