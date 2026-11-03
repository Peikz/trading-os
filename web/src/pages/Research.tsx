// Research (trading_os/research_view.py): the history of your rules, one section at a time.
// Strategy rules, How it was tested, Grades (net of costs, out of sample: the numbers to
// decide on), History (the graded section net of costs, the tables gross), Entries & exits
// (the minute study, gross), Market regime and Study notes. Facts about past rules, not advice.
import { useEffect, useState } from "react";
import {
  api,
  type ChartData,
  type Entries,
  type HistoryQuery,
  type HistoryView,
  type HowTested,
  type Regime,
  type StrategyRules,
  type StudyGrades,
} from "../api";
import { DrawChart } from "../components/DrawChart";
import { Markdown } from "../components/Markdown";
import { ApiTableView, Sections, Table } from "../components/Table";

const SECTIONS = [
  "Strategy rules",
  "How it was tested",
  "Grades",
  "History",
  "Entries & exits",
  "Market regime",
  "Study notes",
] as const;
type Section = (typeof SECTIONS)[number];
const WHAT: Record<Section, string> = {
  "Strategy rules":
    "How every strategy is defined (live scans and the ones tested only), with the exact numbers from the config and how it did in each kind of market.",
  "How it was tested":
    "How every setup was tested on 10 years of data, the best time to buy, where the stop goes, and what makes a trade A+, A, B or C.",
  Grades:
    "Net of costs and out of sample (2019-2026): the grade rules you confirmed and what each grade returned. These are the numbers to decide on.",
  History:
    "Every scan hit in the daily-bar replay. The graded section at the top is net of costs; the tables below it are gross (no costs).",
  "Entries & exits":
    "The minute-bar study: entry, stop and exit per strategy, gross of costs. The grades add the costs.",
  "Market regime": "Whether skipping trades in a weak market would have helped.",
  "Study notes": "Every research write-up from the data repo (docs/research), newest first.",
};

function useLoad<T>(load: () => Promise<T>, deps: unknown[]): [T | null, string | null] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setError(null);
    load().then(
      (d) => live && setData(d),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `load` is rebuilt each render
  }, deps);
  return [data, error];
}

function Loading({ error }: { error: string | null }) {
  return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;
}

export function Research() {
  const [section, setSection] = useState<Section>("Strategy rules");
  return (
    <div>
      <h2>Research</h2>
      <Sections label="Section" options={SECTIONS} value={section} onPick={setSection} />
      <p className="muted">{WHAT[section]}</p>
      {section === "Strategy rules" && <Rules />}
      {section === "How it was tested" && <Tested />}
      {section === "Grades" && <Grades />}
      {section === "History" && <History />}
      {section === "Entries & exits" && <EntriesExits />}
      {section === "Market regime" && <MarketRegime />}
      {section === "Study notes" && <Notes />}
    </div>
  );
}

function Rules() {
  const [label, setLabel] = useState<string | undefined>(undefined);
  const [data, error] = useLoad<StrategyRules>(() => api.strategyRules(label), [label]);
  if (!data) return <Loading error={error} />;
  return (
    <section>
      <select aria-label="Strategy" value={data.label} onChange={(e) => setLabel(e.target.value)}>
        {data.labels.map((l) => (
          <option key={l}>{l}</option>
        ))}
      </select>
      <p>
        <b>{data.heading}</b>
      </p>
      <b>The rules</b>
      <Markdown text={data.rules} />
      {data.settings.length > 0 && (
        <>
          <b>The numbers</b> <span className="muted">(config/scans.yaml; change live scans on the Scans page)</span>
          <Table label="The numbers" columns={["setting", "value"]} rows={data.settings} />
        </>
      )}
      {data.heat.length > 0 && (
        <>
          <b>How it did, per market heat</b> <span className="muted">(net R a trade after costs, its study plan)</span>
          <Table label="Per market heat" columns={Object.keys(data.heat[0])} rows={data.heat} />
        </>
      )}
      {data.heat_note && <p className="muted">{data.heat_note}</p>}
    </section>
  );
}

function Tested() {
  const [data, error] = useLoad<HowTested>(() => api.howTested(), []);
  if (!data) return <Loading error={error} />;
  return (
    <section>
      <h3>The grade rules in config now</h3>
      {data.setups.length === 0 && <p className="muted">No quality grades in config.</p>}
      {data.setups.map((s) => (
        <div key={s.setup} className="rule">
          <b>{s.setup}</b> · {s.grades}
          <ul>
            {s.points.length > 0 && (
              <li>
                <b>Points:</b> {s.points.join(" · ")}
              </li>
            )}
            <li>
              <b>Buy:</b> {s.buy}
            </li>
            <li>
              <b>Stop:</b> {s.stop}
            </li>
            <li>
              <b>Exit:</b> {s.exit}
            </li>
          </ul>
        </div>
      ))}
      {data.setups.length > 0 && <p className="muted">{data.caption}</p>}
      {data.write_up ? (
        <Markdown text={data.write_up} />
      ) : (
        <p className="muted">
          The write-up with the results lives in the private data repo
          (docs/research/how-we-test.md): Pull latest to get it.
        </p>
      )}
    </section>
  );
}

function Grades() {
  const [data, error] = useLoad<StudyGrades>(() => api.studyGrades(), []);
  if (!data) return <Loading error={error} />;
  return (
    <section>
      <p className="muted">
        Each hit of a scan with a scorecard gets the grade its setup earned in the 10-year grading
        study: predicted net R = the strategy's base + the points of each feature - trading costs
        in R, and the bands turn it into a grade. A grade is a fact from the study, never advice.
      </p>
      {data.source ? (
        <p className="muted">
          History: {data.period}. Report: data repo {data.source}.
        </p>
      ) : (
        <p className="muted">The history behind the grades isn't in your data copy yet: Pull latest.</p>
      )}
      <Table label="Size and push per grade" columns={Object.keys(data.sizes[0] ?? {})} rows={data.sizes} />
      <p className="muted">Every other scan: {data.ungraded}.</p>
      {data.strategies.map((s) => (
        <div key={s.title}>
          <h3>{s.title}</h3>
          <ul>
            <li>
              <b>Entry:</b> {s.entry}
            </li>
            <li>
              <b>Stop:</b> {s.stop} · <b>Exit:</b> {s.exit}
            </li>
            <li>
              <b>Grades</b> (predicted net R): {s.bands}; below that C. Base {s.base}
            </li>
          </ul>
          {s.history.length > 0 && (
            <Table label={`${s.title} grades`} columns={Object.keys(s.history[0])} rows={s.history} />
          )}
          <details>
            <summary>Points per feature</summary>
            <Table label={`${s.title} points`} columns={["Feature", "Value", "Points (R)"]} rows={s.features} />
          </details>
        </div>
      ))}
      <details>
        <summary>Trading costs in the score</summary>
        <ul>
          {data.costs.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </details>
      {data.report && (
        <details>
          <summary>The research report</summary>
          <Markdown text={data.report} />
        </details>
      )}
    </section>
  );
}

const STATES = ["strong", "neutral", "weak"];

function History() {
  const [q, setQ] = useState<HistoryQuery>({
    period: "10y",
    strategies: null,
    years: null,
    states: [],
    ep: null,
    split: "none",
    one: null,
  });
  const [data, error] = useLoad<HistoryView>(() => api.history(q), [JSON.stringify(q)]);
  const [byGrade, setByGrade] = useState<string>("");
  const [event, setEvent] = useState<number>(-1);
  if (!data) return <Loading error={error} />;
  const set = <K extends keyof HistoryQuery>(k: K, v: HistoryQuery[K]) => setQ({ ...q, [k]: v });
  const graded = data.graded;
  const gradeNames = graded.summary.rows.map((r) => String(r.strategy));
  const pick = gradeNames.includes(byGrade) ? byGrade : gradeNames[0];
  const ep = q.ep ?? { gap_min: 10, rvol_min: 3, months_min: 0, earnings: "any", must: [] };
  return (
    <section>
      <div className="pills" role="group" aria-label="Period">
        {(["2y", "10y"] as const).map((p) => (
          <button key={p} className={q.period === p ? "on" : ""} onClick={() => setQ({ ...q, period: p, strategies: null, years: null })}>
            {p === "2y" ? "2 years (Massive)" : "10 years (Alpaca, since 2016)"}
          </button>
        ))}
      </div>
      <details open>
        <summary>Net of costs and graded: every strategy, 10 years</summary>
        {graded.summary.rows.length === 0 ? (
          <p className="muted">Not built yet (data repo release grading-10y).</p>
        ) : (
          <>
            <p className="muted">{graded.caption}</p>
            <ApiTableView label="Net of costs and graded" table={graded.summary} />
            <label>
              Grades out of sample (2019-2026) for{" "}
              <select aria-label="Grades for" value={pick} onChange={(e) => setByGrade(e.target.value)}>
                {gradeNames.map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
            <Table
              label="Grades out of sample"
              columns={graded.by_grade.columns.filter((c) => c !== "strategy")}
              rows={graded.by_grade.rows.filter((r) => r.strategy === pick)}
            />
            <p className="muted">
              A+/A/B/C: predicted net R of at least +0.5 / +0.3 / +0.1, else C. daily_mean_r weighs
              every signal day the same: what an account with a few slots could reach.
            </p>
          </>
        )}
      </details>
      {data.empty ? (
        <p className="muted">
          No history here yet. 10 years: the files come from GitHub (is the gh CLI signed in on
          the server?). 2 years: build it with scripts/strategy_history.py and scripts/ep_history.py.
        </p>
      ) : (
        <>
          <p className="muted">{data.caption}</p>
          <div className="row">
            <Multi label="Strategies" options={data.strategies!} value={data.picked!} onChange={(v) => set("strategies", v)} />
            <Multi
              label="Year"
              options={data.years!.map(String)}
              value={data.chosen_years!.map(String)}
              onChange={(v) => set("years", v.map(Number))}
            />
            <Multi label="Breadth state that day" options={STATES} value={q.states} onChange={(v) => set("states", v)} />
          </div>
          {data.picked!.includes("ep_day") && (
            <details>
              <summary>EP-Day filters</summary>
              <div className="row">
                {(
                  [
                    ["gap_min", "Gap at least %"],
                    ["rvol_min", "RVOL at least"],
                    ["months_min", "Months sideways at least"],
                  ] as const
                ).map(([k, lab]) => (
                  <label key={k}>
                    {lab}{" "}
                    <input aria-label={lab} type="number" step="0.5" value={ep[k]} onChange={(e) => set("ep", { ...ep, [k]: Number(e.target.value) })} />
                  </label>
                ))}
                <label>
                  Earnings (inferred){" "}
                  <select aria-label="Earnings (inferred)" value={ep.earnings} onChange={(e) => set("ep", { ...ep, earnings: e.target.value })}>
                    {["any", "yes", "no", "unknown"].map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </select>
                </label>
                <Multi label="Criteria that must pass" options={data.ep_flags!} value={ep.must} onChange={(v) => set("ep", { ...ep, must: v })} />
              </div>
            </details>
          )}
          <label>
            Split by{" "}
            <select aria-label="Split by" value={data.split} onChange={(e) => set("split", e.target.value)}>
              {data.splits!.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <h3>{data.count!.toLocaleString("en-US")} events</h3>
          <ApiTableView label="Summary" table={data.summary} />
          <p className="muted">{data.summary_caption}</p>
          <b>Exits compared</b> <span className="muted">(mean R with the stop; Qullamaggie and Stockbee management)</span>
          <ApiTableView label="Exits compared" table={data.compared} />
          <label>
            Events of{" "}
            <select aria-label="Events of" value={data.one} onChange={(e) => {
              set("one", e.target.value);
              setEvent(-1);
            }}>
              {(data.picked!.length ? data.picked! : data.strategies!).map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <div className="scroll-box">
            <ApiTableView label="Events" table={data.events} />
          </div>
          {data.events!.rows.length > 0 && (
            <label>
              Chart{" "}
              <select aria-label="Event chart" value={event} onChange={(e) => setEvent(Number(e.target.value))}>
                <option value={-1}>—</option>
                {data.events!.rows.map((r, i) => (
                  <option key={i} value={i}>
                    {String(r.session_date)} · {String(r.ticker)}
                  </option>
                ))}
              </select>
            </label>
          )}
          {event >= 0 && data.events!.rows[event] && (
            <EventChart row={data.events!.rows[event]} strategy={data.one!} period={q.period} />
          )}
        </>
      )}
    </section>
  );
}

function Multi({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: string[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <details className="multi">
      <summary>
        {label}: {value.length === options.length ? "all" : value.length ? value.join(", ") : "none"}
      </summary>
      <div className="pills wrap" role="group" aria-label={label}>
        {options.map((o) => (
          <button
            key={o}
            className={value.includes(o) ? "on" : ""}
            onClick={() => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o])}
          >
            {o}
          </button>
        ))}
      </div>
    </details>
  );
}

function EventChart({ row, strategy, period }: { row: Record<string, unknown>; strategy: string; period: string }) {
  const params: Record<string, string> = {
    ticker: String(row.ticker),
    day: String(row.session_date),
    strategy,
    period,
    side: row.side === "short" ? "short" : "long",
  };
  if (typeof row.stop === "number") params.stop = String(row.stop);
  const [data, error] = useLoad<ChartData>(() => api.historyEvent(params), [JSON.stringify(params)]);
  if (!data) return <Loading error={error} />;
  if (!data.candles.length) {
    return <p className="muted">No daily bars for that day here (10 years: they come from GitHub).</p>;
  }
  return (
    <>
      <b>
        {params.ticker} · {strategy} {params.day} · then 63 sessions
      </b>
      <DrawChart data={data} tool="none" height={460} />
    </>
  );
}

function EntriesExits() {
  const [period, setPeriod] = useState<"10y" | "2y">("10y");
  const [p, setP] = useState<Record<string, string>>({});
  const [one, setOne] = useState("");
  const params = { period, ...p };
  const [data, error] = useLoad<Entries>(() => api.entries(params), [JSON.stringify(params)]);
  const [trades, tradesError] = useLoad(
    () => (one ? api.entryTrades(one) : Promise.resolve(null)),
    [one],
  );
  const set = (k: string, v: string) => setP({ ...p, [k]: v });
  return (
    <section>
      <div className="pills" role="group" aria-label="Period">
        {(["2y", "10y"] as const).map((x) => (
          <button key={x} className={period === x ? "on" : ""} onClick={() => {
            setPeriod(x);
            setP({});
          }}>
            {x === "2y" ? "2 years (all trades)" : "10 years (summaries)"}
          </button>
        ))}
      </div>
      {!data && <Loading error={error} />}
      {data && !data.published && (
        <p className="muted">
          {period === "10y"
            ? "The 10-year minute study hasn't been published yet (release intraday-10y)."
            : "No minute study published yet (the data repo's intraday-2y release)."}
        </p>
      )}
      {data?.published && period === "10y" && (
        <>
          <label>
            Minimum trades{" "}
            <input aria-label="Minimum trades" type="number" step="50" min="50" value={p.min_trades ?? "200"} onChange={(e) => set("min_trades", e.target.value)} />
          </label>
          <h3>Best entry, stop and exit per strategy, 10 years</h3>
          <ApiTableView label="Best per strategy" table={data.best} />
          <h3>By year</h3>
          <div className="row">
            <select aria-label="Exit" value={data.exit} onChange={(e) => set("exit", e.target.value)}>
              {data.exits!.map((x) => <option key={x}>{x}</option>)}
            </select>
            <select aria-label="Strategy" value={data.strategy} onChange={(e) => set("strategy", e.target.value)}>
              {data.strategies!.map((x) => <option key={x}>{x}</option>)}
            </select>
          </div>
          <ApiTableView label="By year" table={data.by_year} />
          <p className="muted">
            Mean R per year for exit {data.exit} (groups of 20+ trades). A setup that only works in
            some years shows it here. Facts, not advice.
          </p>
        </>
      )}
      {data?.published && period === "2y" && (
        <>
          <p className="muted">{data.caption}</p>
          <div className="row">
            <label>
              Split by{" "}
              <select aria-label="Split by" value={data.split} onChange={(e) => set("split", e.target.value)}>
                {data.splits!.map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label>
              Minimum trades{" "}
              <input aria-label="Minimum trades" type="number" step="10" min="10" value={p.min_trades ?? "50"} onChange={(e) => set("min_trades", e.target.value)} />
            </label>
          </div>
          <Multi label="Strategies" options={data.strategies!} value={data.picked!} onChange={(v) => set("strategies", v.join(","))} />
          <h3>Best entry, stop and exit per strategy</h3>
          {data.best ? (
            <ApiTableView label="Best per strategy" table={data.best} />
          ) : (
            <p className="muted">Shown for “none” (no split); the table below has every split.</p>
          )}
          <Multi label="Exits in the table" options={data.exits!} value={data.shown!} onChange={(v) => set("exits", v.join(","))} />
          <h3>Every entry and stop</h3>
          <ApiTableView label="Every entry and stop" table={data.table} />
          <label>
            Trades of{" "}
            <select aria-label="Trades of" value={one} onChange={(e) => setOne(e.target.value)}>
              <option value="">—</option>
              {(data.picked!.length ? data.picked! : data.strategies!).map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          {one && (trades ? <ApiTableView label="Trades" table={trades} empty="No trades file for it." /> : <Loading error={tradesError} />)}
        </>
      )}
    </section>
  );
}

function MarketRegime() {
  const [p, setP] = useState<Record<string, string>>({ source: "minute" });
  const [data, error] = useLoad<Regime>(() => api.regime(p), [JSON.stringify(p)]);
  if (!data) return <Loading error={error} />;
  if (!data.published) {
    return <p className="muted">The regime study hasn't been published yet (the data repo's regime-10y release).</p>;
  }
  const set = (k: string, v: string) => {
    const next = { ...p, [k]: v };
    if (k === "strategy" || k === "source") {
      delete next.entry;
      delete next.stop;
    }
    if (k === "entry") delete next.stop;
    setP(next);
  };
  return (
    <section>
      <p className="muted">{data.caption}</p>
      <h3>Market Light per year (% of sessions)</h3>
      <ApiTableView label="Market Light per year" table={data.mix} />
      <div className="pills" role="group" aria-label="Trades">
        {[["minute", "Minute study (entries and stops)"], ["daily", "Daily histories"]].map(([v, t]) => (
          <button key={v} className={p.source === v ? "on" : ""} onClick={() => setP({ source: v })}>
            {t}
          </button>
        ))}
      </div>
      <div className="row">
        <select aria-label="Strategy" value={data.strategy} onChange={(e) => set("strategy", e.target.value)}>
          {data.strategies!.map((x) => <option key={x}>{x}</option>)}
        </select>
        <select aria-label="Exit" value={data.exit} onChange={(e) => set("exit", e.target.value)}>
          {data.exits!.map((x) => <option key={x}>{x}</option>)}
        </select>
        {p.source === "minute" && (
          <>
            <select aria-label="Entry" value={data.entry ?? ""} onChange={(e) => set("entry", e.target.value)}>
              {data.entries!.map((x) => <option key={x}>{x}</option>)}
            </select>
            <select aria-label="Stop" value={data.stop ?? ""} onChange={(e) => set("stop", e.target.value)}>
              {data.stops!.map((x) => <option key={x}>{x}</option>)}
            </select>
          </>
        )}
      </div>
      <h3>Each filter, all years</h3>
      <ApiTableView label="Each filter" table={data.filters} />
      <h3>Year by year (mean R)</h3>
      <ApiTableView label="Year by year" table={data.by_year} />
    </section>
  );
}

function Notes() {
  const [name, setName] = useState<string | undefined>(undefined);
  const [data, error] = useLoad(() => api.studyNotes(name), [name]);
  if (!data) return <Loading error={error} />;
  if (!data.names.length) {
    return <p className="muted">The write-ups live in the private data repo (docs/research): Pull latest.</p>;
  }
  return (
    <section>
      <select aria-label="Study" value={data.name ?? ""} onChange={(e) => setName(e.target.value)}>
        {data.names.map((n) => <option key={n}>{n}</option>)}
      </select>
      {data.text && <Markdown text={data.text} />}
    </section>
  );
}
