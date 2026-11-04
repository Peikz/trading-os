// Your lists' parts, used by the Stocks place: add tickers to a list (typed or a TradingView
// export, each one checked, with feedback), your price alerts (and what fired today), and the
// scans' EP-Watch and BO-Watch. Saved in the data repo; Save & push sends them to GitHub.
import { useEffect, useState } from "react";
import { api, type Alerts, type ScanWatchlists, type WatchAdded } from "../api";
import { Marked, Table } from "../components/Table";
import { readText } from "../format";
import { stripIcons } from "../plain";
import { Icon } from "../ui/Icon";

/** Add typed tickers or a TradingView export to the list `name` (a new name makes a list). */
export function AddToList({ name, onAdded }: { name: string; onAdded: (name: string) => void }) {
  const [typed, setTyped] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [added, setAdded] = useState<WatchAdded | null>(null);
  useEffect(() => setAdded(null), [name]);
  const add = async () => {
    const exportText = file ? await readText(file) : "";
    try {
      const out = await api.addToWatchlist(name, typed, exportText, note);
      setAdded(out);
      if (out.added.length) {
        setTyped("");
        setFile(null);
        onAdded(name.trim());
      }
    } catch (e) {
      setAdded({ kind: "error", added: [], already: [], unknown: [], lines: [(e as Error).message] });
    }
  };
  return (
    <section aria-label="Add to the list">
      <div className="row">
        <input
          aria-label="Add tickers"
          placeholder="Add tickers (comma or space separated)"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
        />
        <input aria-label="Note (optional)" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        <label className="muted">
          or a TradingView export{" "}
          <input aria-label="TradingView export" type="file" accept=".txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <button onClick={add} disabled={!name.trim() || (!typed.trim() && !file)}>
          <Icon name="plus" size={16} />
          Add to list
        </button>
      </div>
      {added && (
        <div className={`msg ${added.kind}`} role="status">
          {added.lines.map((l) => (
            <div key={l}>
              <Marked text={stripIcons(l)} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function PriceAlerts() {
  const [data, setData] = useState<Alerts | null>(null);
  const [ticker, setTicker] = useState("");
  const [level, setLevel] = useState("");
  const [side, setSide] = useState("above");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    api.alerts().then(setData, (e: Error) => setMessage(`Error: ${e.message}`));
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
      (e: Error) => setMessage(`Error: ${e.message}`),
    );

  return (
    <section>
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
      {message && <p className={message.startsWith("Error") ? "error" : "ok"}>{message}</p>}
      {data && data.alerts.length === 0 && <p className="muted">No alerts of your own yet.</p>}
      {data && data.alerts.length > 0 && (
        <Table
          label="Your alerts"
          columns={["ticker", "direction", "level", "note", ""]}
          rows={data.alerts.map((a) => ({ ...a }))}
          render={(c, r) =>
            c === "" ? (
              <button
                className="ghost icon-btn"
                aria-label={`Remove ${r.ticker} ${r.direction} ${r.level}`}
                onClick={() => api.removeAlert(String(r.alert_id)).then(setData)}
              >
                <Icon name="x" size={16} />
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

export function ScanLists({ only }: { only?: string } = {}) {
  const [all, setAll] = useState(false);
  const [data, setData] = useState<ScanWatchlists | null>(null);
  useEffect(() => {
    api.scanWatchlists(all).then(setData, () => setData(null));
  }, [all]);
  const empty = data && Object.values(data).every((w) => w.rows.length === 0);
  return (
    <section>
      <label className="check">
        <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
        Include triggered / expired
      </label>
      {empty && <p className="muted">EP-Watch and BO-Watch fill up as EP and breakout alerts come in.</p>}
      {data &&
        !empty &&
        Object.entries(data)
          .filter(([id]) => !only || id === only)
          .map(([id, w]) => (
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
