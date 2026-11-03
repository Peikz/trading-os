// Watch (the star puts the stock on Flag green, your watchlist; W), a note on the stock (N),
// and a price alert pushed to your phone when the alert watcher sees it trade there.
import { type RefObject, useEffect, useState } from "react";
import { api, type Alert, type StockNote } from "../../api";
import { Icon } from "../../ui/Icon";

export const GREEN = "Flag green";

export function WatchButton({
  watching,
  onToggle,
  compact,
}: {
  watching: boolean;
  onToggle: () => void;
  compact?: boolean;
}) {
  return (
    <button
      className={`${compact ? "ghost icon-btn " : ""}${watching ? "star-on" : ""}`}
      aria-pressed={watching}
      aria-label={watching ? "Watching: remove from your watchlist" : "Watch: add to your watchlist"}
      title="W"
      onClick={onToggle}
    >
      <Icon name="star" filled={watching} />
      {!compact && (watching ? "Watching" : "Watch")}
      {!compact && <kbd>W</kbd>}
    </button>
  );
}

export function WatchNote({
  ticker,
  alertDefault,
  watching,
  onToggleWatch,
  noteRef,
  onMessage,
}: {
  ticker: string;
  alertDefault: number;
  watching: boolean;
  onToggleWatch: () => void;
  noteRef?: RefObject<HTMLTextAreaElement>;
  onMessage: (text: string) => void;
}) {
  const [notes, setNotes] = useState<StockNote[]>([]);
  const [text, setText] = useState("");
  const [level, setLevel] = useState(alertDefault.toFixed(2));
  const [side, setSide] = useState("above");
  const [mine, setMine] = useState<Alert[]>([]);

  useEffect(() => {
    setText("");
    setLevel(alertDefault.toFixed(2));
    api.stockNotes(ticker).then(setNotes, () => setNotes([]));
    api.alerts().then((a) => setMine(a.alerts.filter((x) => x.ticker === ticker)), () => setMine([]));
  }, [ticker, alertDefault]);

  const fail = (e: Error) => onMessage(`Error: ${e.message}`);
  const save = () => {
    if (!text.trim()) return;
    api.addStockNote(ticker, text).then((n) => {
      setNotes(n);
      setText("");
      onMessage("Note saved");
    }, fail);
  };
  const alert = () => {
    const value = Number(level);
    if (!(value > 0)) return;
    api.addAlert(ticker, value, side, "from Today").then((a) => {
      setMine(a.alerts.filter((x) => x.ticker === ticker));
      onMessage(`Alert: ${ticker} ${side} ${value.toFixed(2)} (pushed to your phone when hit)`);
    }, fail);
  };

  return (
    <section className="card" aria-label="Watch and note">
      <div className="watch-row">
        <WatchButton watching={watching} onToggle={onToggleWatch} />
        <span className="muted hint">{watching ? "On your watchlist" : "Not on your watchlist"}</span>
      </div>
      <label className="sr-only" htmlFor={`note-${ticker}`}>
        Note
      </label>
      <textarea
        id={`note-${ticker}`}
        ref={noteRef}
        aria-label="Note"
        rows={3}
        placeholder="Add a note: what you see in this chart (N)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        style={{ marginTop: 12 }}
      />
      <button onClick={save} disabled={!text.trim()}>
        <Icon name="note" size={16} />
        Add note
      </button>
      {notes.length > 0 && (
        <div className="note-list">
          {notes.map((n) => (
            <div key={n.note_id}>
              <span className="muted">{n.note_date}</span> {n.text}
            </div>
          ))}
        </div>
      )}
      <details>
        <summary>
          <Icon name="bell" size={16} />
          &nbsp;Price alert{mine.length ? ` (${mine.length})` : ""}
        </summary>
        <div className="row">
          <input
            aria-label="Alert price"
            type="number"
            step="0.01"
            min="0"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
          />
          <select aria-label="When" value={side} onChange={(e) => setSide(e.target.value)}>
            <option>above</option>
            <option>below</option>
          </select>
          <button onClick={alert}>Add alert</button>
        </div>
        {mine.map((a) => (
          <p key={a.alert_id} className="muted hint">
            Alert {a.direction} {a.level.toFixed(2)}
          </p>
        ))}
        <p className="muted hint">Pushed to your phone once when the alert watcher sees it trade there.</p>
      </details>
    </section>
  );
}
