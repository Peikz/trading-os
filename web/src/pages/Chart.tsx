// The Chart's lower panels (trading_os/chart_view.py): typed-in trend lines (the stock's notes are
// the Notes tab, places/chart/NotesTab.tsx)
// and anchored VWAPs with the saved marks, and minute bars (study days, or live from Alpaca
// when the server has its keys). They sit in the Chart workspace's bottom panel
// (places/ChartWorkspace.tsx), which owns the chart itself.
import { useEffect, useMemo, useState } from "react";
import { api, type ChartData, type Intraday, type IntradayDays } from "../api";
import { IntradayChart } from "../components/IntradayChart";

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
