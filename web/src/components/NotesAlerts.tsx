// Notes & alerts for the stock in focus (app/board.py notes_and_alerts): the 🟩 flag to the
// Flag green watchlist, a note on the stock, and a price alert (pushed to your phone when hit
// by the alert watcher) that starts at the pivot or the plan's entry.
import { type RefObject, useEffect, useState } from "react";
import { api, type Alert, type BoardRow, type StockNote } from "../api";

// Green only (Emil, 4 Nov 2026)
export const FLAGS: [string, string][] = [["🟩", "Flag green"]];

export function NotesAlerts({
  row,
  noteRef,
  onMessage,
}: {
  row: BoardRow;
  noteRef?: RefObject<HTMLTextAreaElement>;
  onMessage: (text: string) => void;
}) {
  const t = row.ticker;
  const start = typeof row.alert_default === "number" ? row.alert_default : 0;
  const [notes, setNotes] = useState<StockNote[]>([]);
  const [text, setText] = useState("");
  const [level, setLevel] = useState(start.toFixed(2));
  const [side, setSide] = useState("above");
  const [mine, setMine] = useState<Alert[]>([]);

  useEffect(() => {
    setLevel(start.toFixed(2));
    api.stockNotes(t).then(setNotes, () => setNotes([]));
    api.alerts().then((a) => setMine(a.alerts.filter((x) => x.ticker === t)), () => setMine([]));
  }, [t, start]);

  const fail = (e: Error) => onMessage(`❌ ${e.message}`);
  const flag = (name: string) => api.flag(t, name).then((r) => onMessage(r.message), fail);
  const save = () => {
    if (!text.trim()) return;
    api.addStockNote(t, text).then((n) => {
      setNotes(n);
      setText("");
      onMessage("Note saved");
    }, fail);
  };
  const alert = () => {
    const value = Number(level);
    if (!(value > 0)) return;
    api.addAlert(t, value, side, "from the focus view").then((a) => {
      setMine(a.alerts.filter((x) => x.ticker === t));
      onMessage(`Alert: ${t} ${side} ${value.toFixed(2)} (pushed to your phone when hit)`);
    }, fail);
  };

  return (
    <section aria-label="Notes and alerts">
      <div className="row">
        {FLAGS.map(([icon, name]) => (
          <button key={name} title={`Add to '${name}'`} aria-label={name} onClick={() => flag(name)}>
            {icon}
          </button>
        ))}
      </div>
      <p className="muted">F flags green. The flags are watchlists (Watchlists page).</p>
      <textarea
        ref={noteRef}
        aria-label="Note"
        rows={3}
        placeholder="N jumps here. What you see in this chart…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button onClick={save} disabled={!text.trim()}>
        Save note
      </button>
      {notes.map((n) => (
        <p key={n.note_id} className="muted">
          {n.note_date}: {n.text}
        </p>
      ))}
      <div className="row">
        <label>
          Alert price{" "}
          <input
            aria-label="Alert price"
            type="number"
            step="0.01"
            min="0"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
          />
        </label>
        <select aria-label="When" value={side} onChange={(e) => setSide(e.target.value)}>
          <option>above</option>
          <option>below</option>
        </select>
        <button onClick={alert}>🔔 Add price alert</button>
      </div>
      {mine.map((a) => (
        <p key={a.alert_id} className="muted">
          🔔 {a.direction} {a.level.toFixed(2)}
        </p>
      ))}
    </section>
  );
}
