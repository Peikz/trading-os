// Scans (trading_os/scans_view.py, scan_editor.py): every scan with when it runs, when its hits
// are pushed, its grade and settings; and Edit a scan: on/off, pushed or saved only, when it
// is pushed, its numbers and switches, its name and note in the push. "Check and save"
// validates the change like the jobs validate config and shows the diff; Commit & push sends
// it to GitHub, where the jobs use it. Only you edit scans; nothing here changes one by itself.
import { useEffect, useState } from "react";
import { api, type ScanForm, type ScansPage } from "../api";
import { Table } from "../components/Table";

const ROW_COLUMNS = ["scan", "on", "runs (NY · CPH)", "pushed", "grade", "settings", "note"];

export function Scans() {
  const [page, setPage] = useState<ScansPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState("");
  const load = () =>
    api.scans().then((p) => {
      setPage(p);
      setPick((x) => x || p.names[0]?.key || "");
    }, (e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);
  if (!page) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;
  return (
    <div>
      <p className="muted">{page.caption}</p>
      <Table label="Scans" columns={ROW_COLUMNS} rows={page.rows} />
      <h3>Edit a scan</h3>
      {page.note && <p className="warn">{page.note}</p>}
      <select aria-label="Scan" value={pick} onChange={(e) => setPick(e.target.value)}>
        {page.names.map((n) => (
          <option key={n.key} value={n.key}>
            {n.label} ({n.key})
          </option>
        ))}
      </select>
      {pick && <Editor key={pick} name={pick} writable={page.writable} onSaved={load} />}
    </div>
  );
}

function Editor({ name, writable, onSaved }: { name: string; writable: boolean; onSaved: () => void }) {
  const [form, setForm] = useState<ScanForm | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<{ message: string; diff: string; ok: boolean } | null>(null);
  useEffect(() => {
    api.scanForm(name).then((f) => {
      setForm(f);
      setValues({
        enabled: f.enabled,
        action: f.action,
        ...(f.push ? { push: f.push } : {}),
        ...Object.fromEntries(f.numbers.map((n) => [n.key, n.value])),
        ...Object.fromEntries(f.flags.map((n) => [n.key, n.value])),
        label: f.push_label,
        note: f.note,
      });
    }, (e: Error) => setResult({ ok: false, message: e.message, diff: "" }));
  }, [name]);
  if (!form) return null;
  const set = (k: string, v: unknown) => setValues((x) => ({ ...x, [k]: v }));
  const save = () =>
    api.saveScan(name, values).then(
      (r) => {
        setResult({ ok: true, message: r.message, diff: r.diff });
        if (r.saved) onSaved();
      },
      (e: Error) => setResult({ ok: false, message: e.message, diff: "" }),
    );
  const commit = () =>
    api.commitScan(name).then(
      (r) => setResult({ ok: r.ok, message: r.message, diff: "" }),
      (e: Error) => setResult({ ok: false, message: e.message, diff: "" }),
    );
  return (
    <section className="form" aria-label="Edit a scan">
      <div className="row">
        <label className="check">
          <input type="checkbox" checked={Boolean(values.enabled)} onChange={(e) => set("enabled", e.target.checked)} />
          On
        </label>
        <div className="pills" role="group" aria-label="Hits">
          {[["push", "pushed"], ["log", "saved only"]].map(([v, t]) => (
            <button key={v} className={values.action === v ? "on" : ""} onClick={() => set("action", v)}>
              {t}
            </button>
          ))}
        </div>
        {form.push && (
          <div className="pills" role="group" aria-label="Pushed">
            {form.push_slots.map((s) => (
              <button key={s} className={values.push === s ? "on" : ""} onClick={() => set("push", s)}>
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="numbers">
        {form.numbers.map((n) => (
          <label key={n.key}>
            {n.key}{" "}
            <input
              aria-label={n.key}
              type="number"
              step={n.kind === "int" ? 1 : "any"}
              value={String(values[n.key] ?? "")}
              onChange={(e) => set(n.key, e.target.value === "" ? n.value : Number(e.target.value))}
            />
          </label>
        ))}
      </div>
      {form.flags.map((f) => (
        <label key={f.key} className="check">
          <input type="checkbox" checked={Boolean(values[f.key])} onChange={(e) => set(f.key, e.target.checked)} />
          {f.key}
        </label>
      ))}
      <input
        aria-label="Name in the push"
        placeholder={form.label}
        value={String(values.label ?? "")}
        onChange={(e) => set("label", e.target.value)}
      />
      <textarea
        aria-label="Note under its section in the push"
        placeholder="Note under its section in the push"
        rows={3}
        value={String(values.note ?? "")}
        onChange={(e) => set("note", e.target.value)}
      />
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
