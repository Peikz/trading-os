// Today's note: the Journal's "Today's note" box (daily_notes.save_for_day: it edits the day's
// note, or adds one; the stocks written as $TICKER are its tags). A collapsible card, on Today
// and at the top of the Journal's Trades tab. Read and saved through /api/journal/daily-notes/today.
import { useEffect, useState } from "react";
import { api, type TodayNote } from "../api";
import { Icon } from "../ui/Icon";

function dayLabel(day: string): string {
  const d = new Date(`${day}T12:00:00`);
  const part = (o: Intl.DateTimeFormatOptions) => d.toLocaleDateString("en-GB", o);
  return `${part({ weekday: "short" })} ${part({ day: "2-digit" })} ${part({ month: "short" })}`;
}

export function DailyNote({ startOpen = false }: { startOpen?: boolean }) {
  const [note, setNote] = useState<TodayNote | null>(null);
  const [text, setText] = useState("");
  const [open, setOpen] = useState(startOpen);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      api.todayNote().then(
        (n) => {
          setNote(n);
          setText(n.text);
        },
        (e: Error) => setMessage(`Error: ${e.message}`),
      );
    load();
    window.addEventListener("trading-os:refresh", load);
    return () => window.removeEventListener("trading-os:refresh", load);
  }, []);

  const save = () =>
    api.saveTodayNote(text).then(
      (n) => {
        setNote(n);
        setMessage("Saved.");
      },
      (e: Error) => setMessage(`Error: ${e.message}`),
    );
  const saved = note?.text ?? "";
  const first = saved.split("\n")[0];
  return (
    <section className="card daily-card" aria-label="Today's note">
      <button
        className="daily-head ghost"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Icon name="note" size={16} />
        <b>Today's note</b>
        <span className="muted">{note ? dayLabel(note.day) : ""}</span>
        {!open && first && <span className="muted preview">{first}</span>}
        <span className="grow" />
        <Icon name={open ? "up" : "down"} size={16} />
      </button>
      {open && (
        <div className="daily-body">
          <textarea
            aria-label="Today's note text"
            rows={4}
            value={text}
            placeholder="How the day went, what you did and why. $TICKER tags a stock."
            onChange={(e) => {
              setText(e.target.value);
              setMessage(null);
            }}
          />
          <div className="row">
            <button className="primary" disabled={!text.trim() || text === saved} onClick={save}>
              Save today's note
            </button>
            {message && <span className={message.startsWith("Error") ? "error" : "ok"}>{message}</span>}
          </div>
        </div>
      )}
    </section>
  );
}
