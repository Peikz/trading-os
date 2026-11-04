// Live results (trading_os/research_view.py): the live signals since launch. Grades live vs
// study (each A+ / A / B signal played out by its study plan, next to the history its grade
// carried, and your trades against the plan), all signals' outcome statistics, and the signals
// you graded with what happened after. Facts, not advice.
import { useEffect, useState } from "react";
import { api, type ApiTable, type LiveGrades } from "../api";
import { ApiTableView, Sections } from "../components/Table";

const SECTIONS = ["Grades live vs study", "All signals", "Signals you graded"] as const;
type Section = (typeof SECTIONS)[number];

export function LiveResults() {
  const [section, setSection] = useState<Section>("Grades live vs study");
  return (
    <div>
      <h3>The live signals since launch</h3>
      <Sections label="Section" options={SECTIONS} value={section} onPick={setSection} />
      <p className="muted">
        The live signals since launch, with what happened 5, 10, 20 and 60 sessions after.
      </p>
      {section === "Grades live vs study" && <Grades />}
      {section === "All signals" && <Stats />}
      {section === "Signals you graded" && <Graded />}
    </div>
  );
}

function Grades() {
  const [data, setData] = useState<LiveGrades | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.liveGrades().then(setData, (e: Error) => setError(e.message));
  }, []);
  if (!data) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;
  return (
    <section>
      <h3>Grades live vs study</h3>
      {data.compare === null ? (
        <p className="muted">
          No live A+ / A / B signals yet. Each one shows here as it comes, with what its plan made,
          next to the history its grade carried.
        </p>
      ) : (
        <>
          <ApiTableView label="Grades live vs study" table={data.compare} />
          <p className="muted">{data.caption}</p>
          <b>Your trades against the plan of the signal they came from</b>
          <ApiTableView
            label="Your trades against the plan"
            table={data.gaps}
            empty="None yet: a closed journal trade bought within two sessions of a live signal."
          />
          <details>
            <summary>Every live signal</summary>
            <ApiTableView label="Every live signal" table={data.signals} />
          </details>
        </>
      )}
      {data.monthly && (
        <p className="muted">Monthly reports: data repo docs/live-tracking/ (newest {data.monthly}).</p>
      )}
    </section>
  );
}

function Stats() {
  const [minimum, setMinimum] = useState<number | undefined>(undefined);
  const [data, setData] = useState<{ minimum: number; total: number; table: ApiTable } | null>(null);
  useEffect(() => {
    api.liveStats(minimum).then(setData, () => setData(null));
  }, [minimum]);
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <section>
      <h3>Outcome statistics</h3>
      <label>
        Minimum signals per group{" "}
        <input
          aria-label="Minimum signals per group"
          type="number"
          min="1"
          max="50"
          value={data.minimum}
          onChange={(e) => setMinimum(Number(e.target.value) || 1)}
        />
      </label>
      <p className="muted">{data.total} outcomes so far</p>
      <ApiTableView label="Outcome statistics" table={data.table} empty="Not enough outcomes yet." />
    </section>
  );
}

function Graded() {
  const [data, setData] = useState<ApiTable | null>(null);
  useEffect(() => {
    api.liveGraded().then(setData, () => setData(null));
  }, []);
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <section>
      <h3>Signals you graded</h3>
      <ApiTableView
        label="Signals you graded"
        table={data}
        empty="Grade signals on the Screener (Stocks from: Scan hits); they show up here with their outcomes."
      />
    </section>
  );
}
