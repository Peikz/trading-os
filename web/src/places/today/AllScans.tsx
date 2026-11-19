// "All scans: every pushed scan's table" (round 4, Streamlit's toggle under Today): one run's scans,
// each as the push shows it: its own columns, the A+/A/B blocks, the facts and the saved chart
// images. Closed until opened; the run is today's newest by default, any run of today or an
// earlier day from the menu.
import { useEffect, useState } from "react";
import { api, type ScanTables, type TodayRuns } from "../../api";
import { ScanTableView } from "../../components/ScanTable";
import { ALL } from "../../shell/todayRun";
import { RunMenu } from "../../ui/RunPicker";

export function AllScans({
  runs,
  earlier,
  picked,
}: {
  runs: TodayRuns | null;
  earlier: { id: string; label: string }[];
  /** The run picked above (or "all"): the table starts on it */
  picked: string;
}) {
  const [open, setOpen] = useState(false);
  const newest = runs?.runs.length ? runs.runs[runs.runs.length - 1].id : (earlier[0]?.id ?? "");
  const [run, setRun] = useState<string | null>(null);
  const id = run ?? (picked !== ALL ? picked : newest);
  const [data, setData] = useState<ScanTables | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !id) return;
    let live = true;
    setData(null);
    setError(null);
    api.scanTables(id).then(
      (d) => live && setData(d),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [open, id]);

  return (
    <section className="all-scans" aria-label="All scans">
      <button className="link toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? "Hide" : "Show"} all scans: every pushed scan&apos;s table
      </button>
      {open && (
        <div className="all-scans-body">
          <div className="row">
            <RunMenu runs={runs} value={id} onPick={setRun} earlier={earlier} noAll />
            {data && <span className="muted">{data.label}</span>}
          </div>
          {error && <p className="error">{error}</p>}
          {!data && !error && <p className="muted">Loading the tables…</p>}
          {data && data.scans.length === 0 && <p className="muted">This run pushed no scans.</p>}
          {data?.scans.map((t) => <ScanTableView key={t.scan} run={data.run} table={t} />)}
        </div>
      )}
    </section>
  );
}
