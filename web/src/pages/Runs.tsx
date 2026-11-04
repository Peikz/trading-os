// Runs (trading_os/runs_view.py, Emil 4 Nov 2026: "see all the push and scan runs and edit
// them", "an overview of it"): every timed run in start order with its times, the scans it runs
// and pushes, on or off; Edit a run's times and on/off in config/runs.yaml; then the scans.
// "Check and save" checks a change like the jobs do (inside the run's New York window) and shows
// the diff; Commit & push sends it to GitHub, whose Timer sync updates the timer by itself.
import { useEffect, useState } from "react";
import { api, type RunForm, type RunsPage } from "../api";
import { Table } from "../components/Table";
import { Scans } from "./Scans";

const COLUMNS = ["run", "on", "starts (NY · CPH)", "second start", "days", "does", "scans", "pushes"];

export function Runs() {
  const [page, setPage] = useState<RunsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState("");
  const [loading, setLoading] = useState(false);
  const load = (started = page?.started ?? false) => {
    setLoading(true);
    return api.timedRuns(started).then(
      (p) => {
        setPage(p);
        setPick((x) => x || p.names[0]?.key || "");
        setLoading(false);
      },
      (e: Error) => {
        setError(e.message);
        setLoading(false);
      },
    );
  };
  useEffect(() => {
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `load` is rebuilt each render
  }, []);
  if (!page) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;
  const columns = page.started ? [...COLUMNS, "last start"] : COLUMNS;
  return (
    <div>
      <p className="muted">{page.caption}</p>
      <Table label="Runs" columns={columns} rows={page.rows} />
      <div className="row">
        <button onClick={() => load(true)} disabled={loading}>
          {loading ? "Asking GitHub…" : "Load how each run last started (GitHub)"}
        </button>
      </div>
      <h3>Edit a run</h3>
      {page.note && <p className="warn">{page.note}</p>}
      <select aria-label="Run" value={pick} onChange={(e) => setPick(e.target.value)}>
        {page.names.map((n) => (
          <option key={n.key} value={n.key}>
            {n.label}
          </option>
        ))}
      </select>
      {pick && <RunEditor key={pick} name={pick} writable={page.writable} onSaved={() => load()} />}
      <h3>Scans</h3>
      <Scans />
    </div>
  );
}

function RunEditor({ name, writable, onSaved }: { name: string; writable: boolean; onSaved: () => void }) {
  const [form, setForm] = useState<RunForm | null>(null);
  const [values, setValues] = useState<{ enabled: boolean; first: string; second: string | null }>({
    enabled: true,
    first: "",
    second: null,
  });
  const [result, setResult] = useState<{ message: string; diff: string; ok: boolean } | null>(null);
  useEffect(() => {
    api.runForm(name).then(
      (f) => {
        setForm(f);
        setValues({ enabled: f.enabled, first: f.first, second: f.second });
      },
      (e: Error) => setResult({ ok: false, message: e.message, diff: "" }),
    );
  }, [name]);
  if (!form) return null;
  const save = () =>
    api.saveRun(name, values.second === null ? { enabled: values.enabled, first: values.first } : values).then(
      (r) => {
        setResult({ ok: true, message: r.message, diff: r.diff });
        if (r.saved) onSaved();
      },
      (e: Error) => setResult({ ok: false, message: e.message, diff: "" }),
    );
  const commit = () =>
    api.commitRun(name).then(
      (r) => setResult({ ok: r.ok, message: r.message, diff: "" }),
      (e: Error) => setResult({ ok: false, message: e.message, diff: "" }),
    );
  return (
    <section className="form" aria-label="Edit a run">
      <div className="row">
        <label className="check">
          <input
            type="checkbox"
            checked={values.enabled}
            onChange={(e) => setValues((x) => ({ ...x, enabled: e.target.checked }))}
          />
          On
        </label>
        <label>
          Starts ({form.clock}, HH:MM){" "}
          <input
            aria-label="Starts"
            value={values.first}
            onChange={(e) => setValues((x) => ({ ...x, first: e.target.value }))}
          />
        </label>
        {values.second !== null && (
          <label>
            Second start, in case the first failed{" "}
            <input
              aria-label="Second start"
              value={values.second}
              onChange={(e) => setValues((x) => ({ ...x, second: e.target.value }))}
            />
          </label>
        )}
      </div>
      {form.window && (
        <p className="muted">
          Both starts must fall inside its New York window, {form.window[0]}-{form.window[1]}, or the run does
          nothing.
        </p>
      )}
      <p className="muted">
        Off: the timer stops starting it and GitHub's backup start exits at once. Started by hand on GitHub, it still
        runs.
      </p>
      <div className="row">
        <button onClick={save} disabled={!writable}>
          Check and save
        </button>
        <button onClick={commit} disabled={!writable}>
          Commit & push to GitHub
        </button>
      </div>
      {result && <p className={result.ok ? "ok" : "error"}>{result.message}</p>}
      {result?.diff && <pre className="diff">{result.diff}</pre>}
    </section>
  );
}
