// The Chart's lower panels (trading_os/chart_view.py): the stock's notes, typed-in trend lines
// and anchored VWAPs with the saved marks, and minute bars (study days, or live from Alpaca
// when the server has its keys). They sit in the Chart workspace's bottom panel
// (places/ChartWorkspace.tsx), which owns the chart itself.
import { useEffect, useMemo, useState } from "react";
import { api, type ChartData, type ChartNotes, type Intraday, type IntradayDays } from "../api";
import { IntradayChart } from "../components/IntradayChart";

const today = () => new Date().toISOString().slice(0, 10);

export function Pills({
  label,
  value,
  options,
  onPick,
}: {
  label: string;
  value: string;
  options: string[][];
  onPick: (v: string) => void;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} className={value === v ? "on" : ""} onClick={() => onPick(v)}>
          {text}
        </button>
      ))}
    </div>
  );
}

export function Notes({ ticker, onMessage }: { ticker: string; onMessage: (t: string) => void }) {
  const [notes, setNotes] = useState<ChartNotes | null>(null);
  const [day, setDay] = useState(today());
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [edit, setEdit] = useState({ text: "", day: "" });
  useEffect(() => {
    api.chartNotes(ticker).then(setNotes, () => setNotes(null));
  }, [ticker]);
  const fail = (e: Error) => onMessage(`Error: ${e.message}`);
  return (
    <section>
      <h3>Notes on {ticker}</h3>
      <div className="row">
        <input aria-label="Note day" type="date" value={day} onChange={(e) => setDay(e.target.value)} />
      </div>
      <textarea aria-label="New note" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      <button
        disabled={!text.trim()}
        onClick={() =>
          api.addChartNote(ticker, text, day).then((n) => {
            setNotes(n);
            setText("");
          }, fail)
        }
      >
        Save note
      </button>
      {notes && notes.notes.length === 0 && <p className="muted">No notes on this stock yet.</p>}
      {notes?.notes.map((n) => (
        <div key={n.note_id} className="note">
          <b>{n.note_date}</b>{" "}
          <span className="muted">
            · written {n.written}
            {n.edited ? ` · edited ${n.edited}` : ""}
          </span>
          {editing === n.note_id ? (
            <div>
              <input aria-label="Edit day" type="date" value={edit.day} onChange={(e) => setEdit({ ...edit, day: e.target.value })} />
              <textarea aria-label="Edit note" rows={3} value={edit.text} onChange={(e) => setEdit({ ...edit, text: e.target.value })} />
              <button
                onClick={() =>
                  api.editChartNote(ticker, n.note_id, edit.text, edit.day).then((x) => {
                    setNotes(x);
                    setEditing(null);
                  }, fail)
                }
              >
                Save
              </button>
              <button onClick={() => setEditing(null)}>Cancel</button>
            </div>
          ) : (
            <>
              <p className="pre">{n.text}</p>
              <button
                className="link"
                onClick={() => {
                  setEditing(n.note_id);
                  setEdit({ text: n.text, day: n.note_date });
                }}
              >
                Edit
              </button>
              <button className="link" onClick={() => api.removeChartNote(ticker, n.note_id).then(setNotes, fail)}>
                Delete
              </button>
            </>
          )}
        </div>
      ))}
      {notes && notes.daily.length > 0 && (
        <>
          <b>From your daily notes ({notes.daily.length})</b>
          {notes.daily.map((n, i) => (
            <div key={i} className="note">
              <b>{n.note_date}</b> · daily note{n.also.length ? ` · also ${n.also.join(" · ")}` : ""}
              <p className="pre">{n.text}</p>
            </div>
          ))}
        </>
      )}
      <p className="muted">
        Notes are kept for good in the data repo (data/journal/stock_notes/): an edit or a delete
        adds a row and never erases the old text. Save & push sends them to GitHub.
      </p>
    </section>
  );
}

export function TypeIn({
  ticker,
  data,
  onSaved,
  onMessage,
}: {
  ticker: string;
  data: ChartData;
  onSaved: () => void;
  onMessage: (t: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const first = data.dates[0] ?? "";
  const [line, setLine] = useState({ d0: first, p0: "", d1: first, p1: "", label: "", extend: true });
  const [anchor, setAnchor] = useState({ day: first, label: "" });
  const fail = (e: Error) => onMessage(`Error: ${e.message}`);
  const dates = useMemo(() => data.dates, [data.dates]);
  return (
    <section>
      <button aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Type in a trend line or an anchor
      </button>
      {open && (
        <div className="form">
          <b>Trend line through two points (extended to today)</b>
          <div className="row">
            <select aria-label="First point: day" value={line.d0} onChange={(e) => setLine({ ...line, d0: e.target.value })}>
              {dates.map((d) => <option key={d}>{d}</option>)}
            </select>
            <input aria-label="First point: price" type="number" step="0.01" value={line.p0} onChange={(e) => setLine({ ...line, p0: e.target.value })} />
            <select aria-label="Second point: day" value={line.d1} onChange={(e) => setLine({ ...line, d1: e.target.value })}>
              {dates.map((d) => <option key={d}>{d}</option>)}
            </select>
            <input aria-label="Second point: price" type="number" step="0.01" value={line.p1} onChange={(e) => setLine({ ...line, p1: e.target.value })} />
          </div>
          <div className="row">
            <input aria-label="Line name (optional)" placeholder="Name (optional)" value={line.label} onChange={(e) => setLine({ ...line, label: e.target.value })} />
            <label className="check">
              <input type="checkbox" checked={line.extend} onChange={(e) => setLine({ ...line, extend: e.target.checked })} />
              Extend to today
            </label>
            <button
              onClick={() =>
                api
                  .addLine(ticker, { x0: line.d0, y0: Number(line.p0), x1: line.d1, y1: Number(line.p1), label: line.label, extend: line.extend })
                  .then(() => {
                    onMessage("Line saved.");
                    onSaved();
                  }, fail)
              }
            >
              Save line
            </button>
          </div>
          <b>Anchored VWAP from a day (an earnings gap, a base high or low)</b>
          <div className="row">
            <select aria-label="Anchor day" value={anchor.day} onChange={(e) => setAnchor({ ...anchor, day: e.target.value })}>
              {dates.map((d) => <option key={d}>{d}</option>)}
            </select>
            <input aria-label="Anchor name (optional)" placeholder="Name (optional)" value={anchor.label} onChange={(e) => setAnchor({ ...anchor, label: e.target.value })} />
            <button
              onClick={() =>
                api.addAnchor(ticker, anchor.day, anchor.label).then(() => {
                  onMessage("Anchor saved.");
                  onSaved();
                }, fail)
              }
            >
              Save anchor
            </button>
          </div>
          {data.marks.length > 0 && (
            <>
              <b>Saved for this stock</b>
              <ul>
                {data.marks.map((m) => (
                  <li key={String(m.mark_id)}>
                    {m.kind === "line"
                      ? `Line ${m.x0} ${Number(m.y0).toFixed(2)} → ${m.x1} ${Number(m.y1).toFixed(2)}`
                      : `AVWAP from ${m.anchor}`}
                    {m.label ? ` · ${m.label}` : ""}{" "}
                    <button
                      className="link"
                      onClick={() =>
                        api.removeMark(ticker, String(m.mark_id)).then(() => onSaved(), fail)
                      }
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}

export function IntradaySection({ ticker }: { ticker: string }) {
  const [on, setOn] = useState(false);
  const [days, setDays] = useState<IntradayDays | null>(null);
  const [source, setSource] = useState<"live" | "study">("live");
  const [day, setDay] = useState("");
  const [every, setEvery] = useState(5);
  const [data, setData] = useState<Intraday | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!on) return;
    api.intradayDays(ticker).then(setDays, (e: Error) => setError(e.message));
  }, [on, ticker]);
  const choices = days ? (source === "live" ? days.live_sessions : days.study_days) : [];
  const picked = choices.includes(day) ? day : (choices[0] ?? "");
  useEffect(() => {
    setData(null);
    setError(null);
    if (!on || !picked || (source === "live" && !days?.live)) return;
    api.intraday(ticker, picked, every, source).then(setData, (e: Error) => setError(e.message));
  }, [on, ticker, picked, every, source, days]);

  return (
    <section>
      <label className="check">
        <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} />
        Intraday (minute bars)
      </label>
      {on && days && (
        <>
          <div className="row">
            <Pills label="Minute bars" value={source} options={[["live", "Live (Alpaca)"], ["study", "Study days"]]} onPick={(v) => setSource(v as "live" | "study")} />
            {choices.length > 0 && (
              <select aria-label="Day" value={picked} onChange={(e) => setDay(e.target.value)}>
                {choices.map((d) => <option key={d}>{d}</option>)}
              </select>
            )}
            <Pills label="Candle" value={String(every)} options={[["1", "1 min"], ["5", "5 min"], ["15", "15 min"]]} onPick={(v) => setEvery(Number(v))} />
          </div>
          {source === "live" && !days.live && <p className="muted">{days.no_keys}</p>}
          {source === "study" && !days.study_days.length && (
            <p className="muted">
              No minute bars for this stock here. They exist for days a strategy could have
              traded it (the minute study's data).
            </p>
          )}
          {error && <p className="error">{error}</p>}
          {data && <IntradayChart data={data} />}
          {data && (
            <p className="muted">
              VWAP from the 09:30 open; pre- and post-market faded.
              {source === "live" &&
                " Alpaca's IEX feed: real-time prices, but its volume is a small part of the market's. Lines: the pivot, stops and plan entry, and the prior close. ▼ 10:30 marks the EP entry time."}
            </p>
          )}
        </>
      )}
    </section>
  );
}
