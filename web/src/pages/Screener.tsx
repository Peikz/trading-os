// The Screener (trading_os/screens.py, the Streamlit Screener page): filters on ~45 fields
// over the last close's universe (or a live TradingView fetch), or over one run's scan hits;
// sort, save and delete your own screens. A screen is a list to look at: no grade, no buy.
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type Filter,
  type RunInfo,
  type ScreenerMeta,
  type ScreenRequest,
  type ScreenResult,
  type ScreenSpec,
  type Value,
} from "../api";
import { GradeBadge } from "../components/Card";
import { formatValue } from "../format";

const NEW = "＋ New screen";
const BLANK: ScreenSpec = { filters: [], sort: "rs_pct", descending: true };

export function Screener() {
  const [meta, setMeta] = useState<ScreenerMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState(NEW);
  const [spec, setSpec] = useState<ScreenSpec>(BLANK);
  const [source, setSource] = useState<"all" | "hits">("all");
  const [live, setLive] = useState(false);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [run, setRun] = useState<string>("");
  const [scans, setScans] = useState<{ id: string; label: string }[]>([]);
  const [scan, setScan] = useState<string>("");
  const [tiers, setTiers] = useState<string[]>(["alert", "log"]);
  const [result, setResult] = useState<ScreenResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");

  useEffect(() => {
    api.screenerMeta().then(setMeta, (e: Error) => setError(e.message));
    api.runs().then((r) => {
      setRuns(r);
      if (r.length) setRun(r[0].id);
    }, () => setRuns([]));
  }, []);

  useEffect(() => {
    if (source !== "hits" || !run) return;
    api.runScans(run).then((r) => {
      const list = Object.entries(r.scans).map(([id, s]) => ({ id, label: s.label }));
      setScans(list);
      setScan((cur) => (list.some((s) => s.id === cur) ? cur : (list[0]?.id ?? "")));
    }, (e: Error) => setError(e.message));
  }, [source, run]);

  const choose = (value: string) => {
    setPick(value);
    if (!meta) return;
    if (value in meta.saved) {
      setSpec(meta.saved[value]);
      setName(value);
    } else if (value.startsWith("Example: ")) {
      setSpec(meta.examples[value.slice("Example: ".length)]);
      setName("");
    } else {
      setSpec(BLANK);
      setName("");
    }
  };

  const go = useCallback(() => {
    const body: ScreenRequest = {
      ...spec,
      source,
      data: live ? "live" : "close",
      run: source === "hits" ? run : null,
      scan: source === "hits" ? scan : null,
      tiers,
    };
    if (source === "hits" && !scan) return;
    setBusy(true);
    setError(null);
    api
      .runScreen(body)
      .then(setResult, (e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }, [spec, source, live, run, scan, tiers]);

  // Re-run shortly after the last change (typing a value runs once, not per key)
  const ready = meta !== null;
  useEffect(() => {
    if (!ready) return;
    const timer = setTimeout(go, 300);
    return () => clearTimeout(timer);
  }, [ready, go]);

  if (!meta) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;

  const fields = Object.keys(meta.fields);
  const setFilter = (i: number, f: Filter) =>
    setSpec((s) => ({ ...s, filters: s.filters.map((x, k) => (k === i ? f : x)) }));

  const save = () =>
    api.saveScreen(name, spec).then(
      (saved) => {
        setMeta({ ...meta, saved });
        setPick(name.trim());
      },
      (e: Error) => setError(e.message),
    );
  const remove = () =>
    api.deleteScreen(pick).then(
      (saved) => {
        setMeta({ ...meta, saved });
        choose(NEW);
      },
      (e: Error) => setError(e.message),
    );

  return (
    <div className="screener">
      <h2>Screener</h2>
      <p className="muted">
        Filter every US stock in the universe, or one scan's hits. A screen of all stocks is a
        list to look at, not a tested setup: no grade, no buy. Scan hits keep their study grade.
      </p>
      <div className="row">
        <select aria-label="Screen" value={pick} onChange={(e) => choose(e.target.value)}>
          <option>{NEW}</option>
          {Object.keys(meta.saved).map((n) => (
            <option key={n}>{n}</option>
          ))}
          {Object.keys(meta.examples).map((n) => (
            <option key={n}>{`Example: ${n}`}</option>
          ))}
        </select>
        <div className="pills" role="group" aria-label="Stocks from">
          <button className={source === "all" ? "on" : ""} onClick={() => setSource("all")}>
            All stocks
          </button>
          <button className={source === "hits" ? "on" : ""} onClick={() => setSource("hits")}>
            Scan hits
          </button>
        </div>
        {source === "all" ? (
          <div className="pills" role="group" aria-label="Data">
            <button className={!live ? "on" : ""} onClick={() => setLive(false)}>
              Last close
            </button>
            <button
              className={live ? "on" : ""}
              onClick={() => setLive(true)}
              title="One TradingView fetch, at most every 5 minutes; history fields from the last close"
            >
              Live now
            </button>
          </div>
        ) : (
          <>
            <select aria-label="Run" value={run} onChange={(e) => setRun(e.target.value)}>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
            <select aria-label="Scan" value={scan} onChange={(e) => setScan(e.target.value)}>
              {scans.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
            {["alert", "log"].map((t) => (
              <label key={t} className="check">
                <input
                  type="checkbox"
                  checked={tiers.includes(t)}
                  onChange={() =>
                    setTiers((x) => (x.includes(t) ? x.filter((y) => y !== t) : [...x, t]))
                  }
                />
                {t}
              </label>
            ))}
          </>
        )}
      </div>

      <h3>Filters</h3>
      {spec.filters.map((f, i) => (
        <FilterRow
          key={i}
          meta={meta}
          fields={fields}
          filter={f}
          onChange={(nf) => setFilter(i, nf)}
          onRemove={() =>
            setSpec((s) => ({ ...s, filters: s.filters.filter((_, k) => k !== i) }))
          }
        />
      ))}
      <div className="row">
        <button
          onClick={() =>
            setSpec((s) => ({
              ...s,
              filters: [...s.filters, { field: "adr20_pct", op: ">=", value: 4 }],
            }))
          }
        >
          ＋ Add filter
        </button>
        {source === "all" ? (
          <>
            <label>
              Sort by{" "}
              <select
                aria-label="Sort by"
                value={spec.sort ?? "rs_pct"}
                onChange={(e) => setSpec({ ...spec, sort: e.target.value })}
              >
                {fields.map((f) => (
                  <option key={f} value={f}>
                    {meta.fields[f].label}
                  </option>
                ))}
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={spec.descending}
                onChange={(e) => setSpec({ ...spec, descending: e.target.checked })}
              />
              Highest first
            </label>
          </>
        ) : (
          <span className="muted">Sorted best study grade first, as in the push.</span>
        )}
      </div>
      <div className="row">
        <input
          aria-label="Screen name"
          placeholder="Name to save as"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button onClick={save} disabled={!name.trim()}>
          Save screen
        </button>
        {pick in meta.saved && <button onClick={remove}>Delete '{pick}'</button>}
      </div>

      {error && <p className="error">{error}</p>}
      {busy && <p className="muted">Running…</p>}
      {result && <Results meta={meta} result={result} />}
    </div>
  );
}

function FilterRow({
  meta,
  fields,
  filter,
  onChange,
  onRemove,
}: {
  meta: ScreenerMeta;
  fields: string[];
  filter: Filter;
  onChange: (f: Filter) => void;
  onRemove: () => void;
}) {
  const kind = meta.fields[filter.field]?.kind ?? "num";
  const ops = meta.ops[kind];
  const [options, setOptions] = useState<string[]>([]);
  useEffect(() => {
    if (kind === "text") api.options(filter.field).then(setOptions, () => setOptions([]));
  }, [kind, filter.field]);

  const num = (v: string): number | null => (v === "" ? null : Number(v));
  const pair = Array.isArray(filter.value) ? filter.value : [null, null];

  return (
    <div className="row filter">
      <select
        aria-label="Field"
        value={filter.field}
        onChange={(e) => {
          const k = meta.fields[e.target.value].kind;
          const first = meta.ops[k][0];
          onChange({ field: e.target.value, op: first, value: k === "text" ? [] : null });
        }}
      >
        {fields.map((f) => (
          <option key={f} value={f}>
            {meta.fields[f].group} · {meta.fields[f].label}
          </option>
        ))}
      </select>
      <select
        aria-label="Operator"
        value={filter.op}
        onChange={(e) => onChange({ ...filter, op: e.target.value, value: null })}
      >
        {ops.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
      {filter.op === "between" ? (
        <>
          <input
            aria-label="From"
            type="number"
            value={(pair[0] as number | null) ?? ""}
            onChange={(e) => onChange({ ...filter, value: [num(e.target.value), pair[1]] })}
          />
          <input
            aria-label="To"
            type="number"
            value={(pair[1] as number | null) ?? ""}
            onChange={(e) => onChange({ ...filter, value: [pair[0], num(e.target.value)] })}
          />
        </>
      ) : filter.op.startsWith("is ") && kind === "text" ? (
        <select
          aria-label="Values"
          multiple
          value={(filter.value as string[] | null) ?? []}
          onChange={(e) =>
            onChange({
              ...filter,
              value: Array.from(e.target.selectedOptions, (o) => o.value),
            })
          }
        >
          {options.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      ) : kind === "bool" ? null : (
        <input
          aria-label="Value"
          type="number"
          value={(filter.value as number | null) ?? ""}
          onChange={(e) => onChange({ ...filter, value: num(e.target.value) })}
        />
      )}
      <button onClick={onRemove} title="Remove this filter" aria-label="Remove filter">
        ✕
      </button>
    </div>
  );
}

function Results({ meta, result }: { meta: ScreenerMeta; result: ScreenResult }) {
  const label = (c: string) =>
    c === "ticker" ? "Ticker" : c === "grade" ? "Grade" : (meta.fields[c]?.label ?? c);
  return (
    <section>
      <p>
        <b>{result.count} stocks</b> from {result.when}
        <br />
        <span className="muted">{result.summary}</span>
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {result.columns.map((c) => (
                <th key={c}>{label(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((r, i) => (
              <tr key={`${r.ticker}-${i}`}>
                {result.columns.map((c) => (
                  <td key={c}>
                    {c === "grade" && typeof r[c] === "string" ? (
                      <GradeBadge grade={r[c] as string} />
                    ) : c === "ticker" ? (
                      <b>{r[c] as string}</b>
                    ) : (
                      formatValue(r[c] as Value, meta.fields[c]?.kind)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result.rows.length < result.count && (
        <p className="muted">The first {result.rows.length} shown.</p>
      )}
    </section>
  );
}
