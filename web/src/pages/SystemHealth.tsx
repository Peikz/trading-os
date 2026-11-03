// System health (trading_os/health.py, timer.py, validation.py): which scheduled job ran for
// which session, data freshness, failure logs, the data cache, whether each timed job started
// on time and how late GitHub started each run; and a run checked against a TradingView
// screener export, appended to docs/validation.md in the data repo.
import { useEffect, useState } from "react";
import { api, type ApiTable, type Jobs } from "../api";
import { ApiTableView, Sections } from "../components/Table";

const SECTIONS = ["Jobs and data", "Validation against TradingView"] as const;
type Section = (typeof SECTIONS)[number];

export function SystemHealth() {
  const [section, setSection] = useState<Section>("Jobs and data");
  return (
    <div>
      <h2>System health</h2>
      <Sections label="Section" options={SECTIONS} value={section} onPick={setSection} />
      {section === "Jobs and data" ? <JobsAndData /> : <Validation />}
    </div>
  );
}

function JobsAndData() {
  const [data, setData] = useState<Jobs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [gh, setGh] = useState<{ answered: boolean; timer?: ApiTable; runs?: ApiTable } | null>(null);
  const [loadingGh, setLoadingGh] = useState(false);
  useEffect(() => {
    api.jobs().then(setData, (e: Error) => setError(e.message));
  }, []);
  if (!data) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;
  return (
    <section>
      <p className="muted">From the dashboard's copy of the data repo: Pull latest first to see the latest runs.</p>
      <h3>Runs per session</h3>
      <ApiTableView label="Runs per session" table={data.grid} />
      <p className="muted">
        ✅ the scheduled run saved its output · 🟡 only a manual run · ❌ nothing · ⏳ not due yet.
        pm 07:15-07:55, am 10:10-11:30, mid 11:55-13:30, eod 16:15-23:59 ET.
      </p>
      <h3>Data freshness</h3>
      <ApiTableView label="Data freshness" table={data.freshness} />
      <h3>Failures (newest first)</h3>
      <ApiTableView label="Failures" table={data.failures} empty="✅ No failure logs." />
      <h3>Data cache</h3>
      <p className="muted">
        The study data lives on GitHub; the dashboard keeps only what was opened ({data.cache.used_gb} of{" "}
        {data.cache.limit_gb} GB; least used files go first).
      </p>
      <button onClick={() => api.clearCache().then((r) => setMessage(r.message), (e: Error) => setMessage(`❌ ${e.message}`))}>
        Empty the cache
      </button>
      {message && <p className={message.startsWith("❌") ? "error" : "ok"}>{message}</p>}
      <h3>Timer and GitHub runs</h3>
      <button
        disabled={loadingGh}
        onClick={() => {
          setLoadingGh(true);
          api.github().then(setGh, () => setGh({ answered: false })).finally(() => setLoadingGh(false));
        }}
      >
        Load the latest runs from GitHub
      </button>
      {gh && !gh.answered && <p className="warn">No answer from GitHub (is the gh CLI installed and signed in where the dashboard runs?).</p>}
      {gh?.answered && (
        <>
          <b>Did each timed job start on time?</b>
          <ApiTableView label="Timer" table={gh.timer} />
          <p className="muted">
            The cron-job.org timer starts each job at its New York time; GitHub's own schedule is
            the backup. Late: started after 10 minutes. Missed: no start before the job's window
            closed (2 hours for the jobs without one). If every job is missed, the timer stopped:
            check cron-job.org's email, or a GitHub token that expired (see the Guide).
          </p>
          <b>Latest runs</b>
          <ApiTableView label="Latest runs" table={gh.runs} />
          <p className="muted">
            minutes_late: how long after its cron GitHub started a scheduled run. A run that starts
            after its window closes exits without scanning.
          </p>
        </>
      )}
    </section>
  );
}

function Validation() {
  const [choices, setChoices] = useState<{ runs: { id: string; label: string }[]; scans: { id: string; label: string }[] } | null>(null);
  const [run, setRun] = useState("");
  const [scan, setScan] = useState("ep_day");
  const [csv, setCsv] = useState<string>("");
  const [result, setResult] = useState<ApiTable | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    api.validationRuns().then((c) => {
      setChoices(c);
      setRun(c.runs[0]?.id ?? "");
    }, (e: Error) => setMessage(`❌ ${e.message}`));
  }, []);
  useEffect(() => {
    setResult(null);
    if (!csv || !run) return;
    api.validate({ run, scan, csv_text: csv }).then(setResult, (e: Error) => setMessage(`❌ ${e.message}`));
  }, [csv, run, scan]);
  if (!choices) return message ? <p className="error">{message}</p> : <p className="muted">Loading…</p>;
  if (!choices.runs.length) return <p className="muted">No runs yet.</p>;
  return (
    <section>
      <div className="row">
        <select aria-label="Run" value={run} onChange={(e) => setRun(e.target.value)}>
          {choices.runs.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
        </select>
        <select aria-label="Scan" value={scan} onChange={(e) => setScan(e.target.value)}>
          {choices.scans.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
        <label>
          TradingView screener export (CSV){" "}
          <input
            aria-label="TradingView screener export"
            type="file"
            accept=".csv"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) f.text().then(setCsv);
            }}
          />
        </label>
      </div>
      {result && (
        <>
          <ApiTableView label="Validation" table={result} empty="Nothing found on either side." />
          <button
            onClick={() =>
              api.appendValidation({ run, scan, csv_text: csv }).then((r) => setMessage(r.message), (e: Error) => setMessage(`❌ ${e.message}`))
            }
          >
            Append to docs/validation.md
          </button>
        </>
      )}
      {message && <p className={message.startsWith("❌") ? "error" : "ok"}>{message}</p>}
    </section>
  );
}
