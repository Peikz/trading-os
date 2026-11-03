// Chart (trading_os/chart_view.py): any stock, interactive. Daily or weekly bars, 2 or 10 years,
// MA 10/20/50/200 and EMA 9/21, the scans' past hits, your buys and sells, the pivot, stops and
// plan entry, anchored VWAPs (quick ones or any day you save), trend lines you draw, move or
// erase (or type in), the stock's notes, and minute bars (study days, or live from Alpaca when
// the server has its keys). `#/chart?t=TICKER` opens a stock directly.
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type ChartData,
  type ChartNotes,
  type ChartQuery,
  type Intraday,
  type IntradayDays,
  type TrendLine,
} from "../api";
import { DrawChart, type Point, type Tool } from "../components/DrawChart";
import { IntradayChart } from "../components/IntradayChart";

const LINES = ["MA10", "MA20", "MA50", "MA200", "EMA9", "EMA21"];
const SPANS = ["3M", "6M", "1Y", "2Y", "All"];
const TOOLS: [Tool, string, string][] = [
  ["none", "🖐", "Pan and zoom"],
  ["draw", "✏️", "Draw a trend line (two clicks)"],
  ["move", "✋", "Move a line's end (drag)"],
  ["erase", "🧽", "Delete the line you click"],
];

/** The ticker in `#/chart?t=XXX`. */
export function hashTicker(hash: string): string {
  const q = hash.split("?")[1] ?? "";
  return (new URLSearchParams(q).get("t") ?? "").trim().toUpperCase();
}

const today = () => new Date().toISOString().slice(0, 10);

export function Chart() {
  const [picks, setPicks] = useState<{ ticker: string; where: string }[]>([]);
  const [quick, setQuick] = useState("");
  const [typed, setTyped] = useState(() => hashTicker(window.location.hash));
  const ticker = (typed.trim() || quick).toUpperCase();
  const [q, setQ] = useState<ChartQuery>({
    period: "2y",
    timeframe: "Daily",
    span: "1Y",
    lines: ["MA10", "MA20", "MA50"],
    hits: true,
    fills: true,
    levels: true,
    anchors: [],
  });
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("none");
  const [flash, setFlash] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api.chartPicks().then(setPicks, () => setPicks([]));
  }, []);
  useEffect(() => {
    const on = () => {
      const t = hashTicker(window.location.hash);
      if (t) setTyped(t);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  useEffect(() => {
    if (!ticker) return setData(null);
    let live = true;
    setError(null);
    const timer = setTimeout(() => {
      api.chart(ticker, q).then(
        (d) => live && setData(d),
        (e: Error) => live && setError(e.message),
      );
    }, 250);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [ticker, q, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const fail = (e: Error) => setFlash(`❌ ${e.message}`);
  const set = <K extends keyof ChartQuery>(k: K, v: ChartQuery[K]) => setQ((x) => ({ ...x, [k]: v }));
  const toggle = (k: "lines" | "anchors", v: string) =>
    setQ((x) => ({ ...x, [k]: x[k].includes(v) ? x[k].filter((y) => y !== v) : [...x[k], v] }));

  const draw = (a: Point, b: Point, extend: boolean) =>
    api.addLine(ticker, { x0: a.time, y0: a.price, x1: b.time, y1: b.price, extend }).then(() => {
      setFlash("Line saved.");
      reload();
    }, fail);
  const move = (l: TrendLine, a: Point, b: Point) =>
    api.moveLine(ticker, l.id, { x0: a.time, y0: a.price, x1: b.time, y1: b.price, extend: l.extend }).then(() => {
      setFlash("Line moved.");
      reload();
    }, fail);
  const erase = (l: TrendLine) =>
    api.removeMark(ticker, l.id).then(() => {
      setFlash("Line deleted.");
      reload();
    }, fail);

  const daily = q.timeframe === "Daily";
  return (
    <div>
      <h2>Chart</h2>
      <div className="row">
        <select aria-label="Today's hits, watchlists, open positions" value={quick} onChange={(e) => {
          setQuick(e.target.value);
          setTyped("");
        }}>
          <option value="">Today's hits (pushed first), watchlists, open positions</option>
          {picks.map((p) => (
            <option key={p.ticker} value={p.ticker}>
              {p.ticker} ({p.where})
            </option>
          ))}
        </select>
        <input
          aria-label="Any ticker"
          placeholder="…or type any ticker"
          value={typed}
          onChange={(e) => setTyped(e.target.value.toUpperCase())}
        />
      </div>
      {!ticker && <p className="muted">Pick or type a ticker.</p>}
      {ticker && (
        <>
          <div className="row">
            <Pills label="History" value={q.period} options={[["2y", "2 years"], ["10y", "10 years"]]} onPick={(v) => set("period", v)} />
            <Pills label="Bars" value={q.timeframe} options={[["Daily", "Daily"], ["Weekly", "Weekly"]]} onPick={(v) => set("timeframe", v)} />
            <Pills label="Show" value={q.span} options={SPANS.map((s) => [s, s])} onPick={(v) => set("span", v)} />
          </div>
          <div className="row">
            <div className="pills" role="group" aria-label="Lines">
              {LINES.map((l) => (
                <button key={l} className={q.lines.includes(l) ? "on" : ""} onClick={() => toggle("lines", l)}>
                  {l}
                </button>
              ))}
            </div>
            {(["hits", "fills", "levels"] as const).map((k) => (
              <label key={k} className="check">
                <input type="checkbox" checked={q[k]} onChange={(e) => set(k, e.target.checked)} />
                {{ hits: "Scan hits", fills: "My trades", levels: "Pivot and stops" }[k]}
              </label>
            ))}
          </div>
          {data && Object.keys(data.quick_anchors).length > 0 && (
            <div className="pills" role="group" aria-label="Anchored VWAP from">
              <span className="muted">AVWAP from</span>
              {Object.entries(data.quick_anchors).map(([name, day]) => (
                <button key={name} title={day} className={q.anchors.includes(name) ? "on" : ""} onClick={() => toggle("anchors", name)}>
                  {name}
                </button>
              ))}
            </div>
          )}
          {error && <p className="error">{error}</p>}
          {data && data.ticker === ticker && (
            <>
              {daily && (
                <div className="pills" role="group" aria-label="Tools">
                  {TOOLS.map(([id, icon, title]) => (
                    <button key={id} title={title} aria-label={title} className={tool === id ? "on" : ""} onClick={() => setTool(id)}>
                      {icon}
                    </button>
                  ))}
                </div>
              )}
              {data.candles.length ? (
                <DrawChart data={data} tool={daily ? tool : "none"} onDraw={draw} onMove={move} onErase={erase} />
              ) : (
                <p className="muted">No daily bars for {ticker} in the data repo.</p>
              )}
              {/* Under the chart, so a message never moves the chart you are drawing on */}
              {flash && <p className="flash" role="status">{flash}</p>}
              <p className="muted">{data.note}</p>
              <a href={data.tradingview} target="_blank" rel="noreferrer">
                Open in TradingView
              </a>
              <Notes ticker={ticker} onMessage={setFlash} />
              <TypeIn ticker={ticker} data={data} onSaved={reload} onMessage={setFlash} />
              <IntradaySection ticker={ticker} />
            </>
          )}
        </>
      )}
    </div>
  );
}

function Pills({
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
    <div className="pills" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} className={value === v ? "on" : ""} onClick={() => onPick(v)}>
          {text}
        </button>
      ))}
    </div>
  );
}

function Notes({ ticker, onMessage }: { ticker: string; onMessage: (t: string) => void }) {
  const [notes, setNotes] = useState<ChartNotes | null>(null);
  const [day, setDay] = useState(today());
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [edit, setEdit] = useState({ text: "", day: "" });
  useEffect(() => {
    api.chartNotes(ticker).then(setNotes, () => setNotes(null));
  }, [ticker]);
  const fail = (e: Error) => onMessage(`❌ ${e.message}`);
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

function TypeIn({
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
  const fail = (e: Error) => onMessage(`❌ ${e.message}`);
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

function IntradaySection({ ticker }: { ticker: string }) {
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
