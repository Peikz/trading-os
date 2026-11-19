// The Journal place (trading_os/journal_view.py, positions_view.py, research_view.py), one tab at
// a time: Trades (the closed trades with the selected trade beside them: chart with your fills,
// grade, conviction and notes; today's note; the broker export upload; log a fill), Positions (a
// card per open position, then the journal's open table and what each plan says), Plans, Notes
// (daily notes) and Live results (your real R per setup and the live signals against the study).
// Private: it stays in the data repo. Facts, not advice.
import { useEffect, useState } from "react";
import {
  api,
  type JournalOpen,
  type JournalPlans,
  type Suggestion,
  type Table as TableData,
} from "../api";
import { DailyNote } from "../components/DailyNote";
import { Notebook } from "../notebook/Notebook";
import { Table } from "../components/Table";
import { Icon } from "../ui/Icon";
import { ImportDialog } from "./journal/ImportDialog";
import { Trades } from "./journal/Trades";
import { LiveResults } from "./LiveResults";
import { Positions } from "./Positions";

const OPEN_COLUMNS = [
  "ticker", "direction", "entry_date", "entry_avg", "open_quantity", "order_stop",
  "last_close", "last_date", "open_pnl", "open_r", "at_risk_usd", "at_risk_pct", "setup",
];
const PLAN_COLUMNS = [
  "status", "session_date", "ticker", "direction", "setup", "entry", "stop", "shares",
  "risk_usd", "fill_date", "fill_price", "slippage_pct", "slippage_r", "note", "plan_id",
];

export function Journal({ tab = "trades", params }: { tab?: string; params?: URLSearchParams }) {
  const [importing, setImporting] = useState(false);
  return (
    <div>
      {tab === "trades" && (
        <>
          <div className="journal-bar">
            <p className="muted">
              Fills are the record: imported from the broker or logged here by hand (a broker fill
              later replaces the matching hand-logged one). Private: stays in the data repo.
            </p>
            <button onClick={() => setImporting(true)}>
              <Icon name="upload" size={16} />
              Import broker fills
            </button>
          </div>
          <DailyNote />
          <details className="log-fill">
            <summary>Log a fill by hand</summary>
            <LogTab />
          </details>
          <Trades />
          {importing && (
            <ImportDialog
              onClose={() => setImporting(false)}
              onImported={() => window.dispatchEvent(new Event("trading-os:journal"))}
            />
          )}
        </>
      )}
      {tab === "positions" && (
        <>
          <Positions />
          <h3>Open positions in the journal</h3>
          <OpenTab />
        </>
      )}
      {tab === "plans" && <PlansTab />}
      {tab === "notes" && <Notebook params={params ?? new URLSearchParams()} />}
      {tab === "live" && (
        <>
          <h3>Your real R per setup against the study</h3>
          <RealTab />
          <LiveResults />
        </>
      )}
    </div>
  );
}

function useLoad<T>(load: () => Promise<T>): [T | null, string | null] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    load().then(setData, (e: Error) => setError(e.message));
  }, [load]);
  return [data, error];
}

function OpenTab() {
  const [data, error] = useLoad<JournalOpen>(api.journalOpen);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!data.rows.length) {
    return <p className="muted">No open positions. Log an entry under “Log a trade” or import fills.</p>;
  }
  // The totals (count, P&L, at risk) are on the Positions cards above; only the rows are here.
  return (
    <section>
      <Table label="Open positions" columns={OPEN_COLUMNS} rows={data.rows} />
      <p className="muted">Valued at the newest daily close in the data repo, not live prices.</p>
      {data.plan_day && (
        <>
          <b>What each plan says (at the {data.plan_day} close)</b>
          <Table
            label="What each plan says"
            columns={["ticker", "setup", "rule", "held", "hold", "r_now", "earnings", "action"]}
            rows={data.plan}
          />
          <p className="muted">{data.plan_caption}</p>
        </>
      )}
    </section>
  );
}

const today = () => new Date().toISOString().slice(0, 10);

function LogTab() {
  const [setups] = useLoad<string[]>(api.journalSetups);
  const [form, setForm] = useState({
    date: today(), ticker: "", side: "buy", shares: "", price: "", fees: "", setup: "", stop: "",
  });
  const [message, setMessage] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });
  const save = () =>
    api
      .logFill({
        date: form.date,
        ticker: form.ticker.trim().toUpperCase(),
        side: form.side,
        shares: Number(form.shares),
        price: Number(form.price),
        fees: Number(form.fees || 0),
        setup: form.setup || null,
        stop: form.stop ? Number(form.stop) : null,
      })
      .then(
        (r) => {
          setMessage(r.message);
          setForm({ ...form, ticker: "", shares: "", price: "", fees: "", stop: "" });
        },
        (e: Error) => setMessage(`Error: ${e.message}`),
      );
  return (
    <section className="form">
      <b>Log a fill (an entry, an add, a partial sell or the exit)</b>
      <div className="row">
        <input aria-label="Date" type="date" value={form.date} onChange={set("date")} />
        <input aria-label="Ticker" placeholder="Ticker" value={form.ticker} onChange={set("ticker")} />
        <select aria-label="Side" value={form.side} onChange={set("side")}>
          <option>buy</option>
          <option>sell</option>
        </select>
      </div>
      <div className="row">
        <input aria-label="Shares" type="number" min="0" placeholder="Shares" value={form.shares} onChange={set("shares")} />
        <input aria-label="Price" type="number" min="0" step="0.0001" placeholder="Price" value={form.price} onChange={set("price")} />
        <input aria-label="Fees" type="number" min="0" step="0.5" placeholder="Fees" value={form.fees} onChange={set("fees")} />
      </div>
      <div className="row">
        <select aria-label="Setup" value={form.setup} onChange={set("setup")}>
          <option value="">Setup</option>
          {(setups ?? []).map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <input
          aria-label="Initial stop (entries)"
          type="number"
          min="0"
          step="0.0001"
          placeholder="Initial stop (entries)"
          value={form.stop}
          onChange={set("stop")}
        />
        <button onClick={save}>Save fill</button>
      </div>
      {message && <p className={message.startsWith("Error") ? "error" : "ok"}>{message}</p>}
    </section>
  );
}

function PlansTab() {
  const [data, setData] = useState<JournalPlans | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [from, setFrom] = useState("");
  const [form, setForm] = useState({
    session: "", ticker: "", direction: "long", entry: "", stop: "", setup: "", shares: "", note: "",
  });
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [cancel, setCancel] = useState("");

  useEffect(() => {
    api.journalPlans().then((d) => {
      setData(d);
      setForm((f) => ({ ...f, session: f.session || d.today }));
    }, (e: Error) => setError(e.message));
  }, []);

  // The suggested shares follow the entry and the stop
  const { entry, stop } = form;
  useEffect(() => {
    const e = Number(entry);
    const s = Number(stop);
    if (!(e > 0 && s > 0)) return setSuggestion(null);
    const timer = setTimeout(() => {
      api.suggest(e, s).then((r) => {
        setSuggestion(r);
        if (r.suggestion) setForm((f) => ({ ...f, shares: String(r.suggestion!.shares) }));
      }, () => setSuggestion(null));
    }, 250);
    return () => clearTimeout(timer);
  }, [entry, stop]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });
  const prefill = (label: string) => {
    setFrom(label);
    const hit = data.hits.find((h) => h.label === label);
    if (!hit) return;
    setForm({
      ...form,
      ticker: hit.ticker,
      entry: String(hit.plan_entry),
      stop: String(hit.plan_stop),
      setup: data.setups.includes(hit.scan) ? hit.scan : "",
    });
  };
  const save = () =>
    api
      .createPlan({
        session: form.session,
        ticker: form.ticker.trim().toUpperCase(),
        direction: form.direction,
        entry: Number(form.entry),
        stop: Number(form.stop),
        shares: Number(form.shares || 0),
        setup: form.setup || null,
        note: form.note,
      })
      .then(
        (d) => {
          setData(d);
          setMessage(d.message ?? "Plan saved.");
          setFrom("");
        },
        (e: Error) => setMessage(`Error: ${e.message}`),
      );
  const openIds = data.plans.filter((p) => p.status === "open").map((p) => String(p.plan_id));

  return (
    <section className="form">
      <label>
        Start from a scan hit (latest run){" "}
        <select aria-label="Start from a scan hit" value={from} onChange={(e) => prefill(e.target.value)}>
          <option value="">—</option>
          {data.hits.map((h) => (
            <option key={h.label}>{h.label}</option>
          ))}
        </select>
      </label>
      <b>New plan</b>
      <div className="row">
        <input aria-label="For session" type="date" value={form.session} onChange={set("session")} />
        <input aria-label="Plan ticker" placeholder="Ticker" value={form.ticker} onChange={set("ticker")} />
        <select aria-label="Direction" value={form.direction} onChange={set("direction")}>
          <option>long</option>
          <option>short</option>
        </select>
      </div>
      <div className="row">
        <input aria-label="Entry" type="number" min="0" step="0.0001" placeholder="Entry" value={form.entry} onChange={set("entry")} />
        <input aria-label="Stop" type="number" min="0" step="0.0001" placeholder="Stop" value={form.stop} onChange={set("stop")} />
        <select aria-label="Plan setup" value={form.setup} onChange={set("setup")}>
          <option value="">Setup</option>
          {data.setups.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>
      <div className="row">
        <input
          aria-label="Shares (suggested from your risk per trade)"
          type="number"
          min="0"
          placeholder="Shares"
          value={form.shares}
          onChange={set("shares")}
        />
        <input aria-label="Plan note" placeholder="Note" value={form.note} onChange={set("note")} />
        <button onClick={save}>Save plan</button>
      </div>
      {suggestion?.text && <p className="muted">{suggestion.text}</p>}
      {message && <p className={message.startsWith("Error") ? "error" : "ok"}>{message}</p>}
      {data.plans.length === 0 ? (
        <p className="muted">No plans yet.</p>
      ) : (
        <Table label="Plans" columns={PLAN_COLUMNS} rows={data.plans} />
      )}
      {openIds.length > 0 && (
        <div className="row">
          <select aria-label="Cancel an open plan" value={cancel} onChange={(e) => setCancel(e.target.value)}>
            <option value="">Cancel an open plan</option>
            {openIds.map((id) => (
              <option key={id}>{id}</option>
            ))}
          </select>
          <button
            disabled={!cancel}
            onClick={() => api.cancelPlan(cancel).then(setData, (e: Error) => setMessage(`Error: ${e.message}`))}
          >
            Cancel plan
          </button>
        </div>
      )}
    </section>
  );
}

function RealTab() {
  const [data, error] = useLoad<TableData>(api.realVsStudy);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!data.rows.length) return <p className="muted">Your real R per setup shows here once trades are closed.</p>;
  return (
    <section>
      <Table label="Real vs study" columns={data.columns} rows={data.rows} />
      <p className="muted">{data.caption}</p>
    </section>
  );
}
