// A scan's own table in the Screener's Scan hits page (round 4, Streamlit's `show_table` and
// `grade_blocks`): the scan's own columns (its gap, pace, pivot and so on) with the study grade,
// why, predicted R, short interest, IBD tag and volume build, then the A+ / A / B blocks as the
// push shows them. On "All today" it reads the newest run of today that had the scan.
import { useEffect, useState } from "react";
import { api, type ScanTable, type TodayRuns } from "../../api";
import { blockLine, ScanTableView } from "../../components/ScanTable";
import { ALL } from "../../shell/todayRun";

/** The run a scan's table is read from: the picked run; on "All today" the newest run of today that
 * had the scan (`slots`: the slots its hits came from), else today's newest. */
export function tableRun(run: string, runs: TodayRuns | null, slots: string[] = []): string {
  if (run !== ALL) return run;
  const list = runs?.runs ?? [];
  const had = [...list].reverse().find((r) => slots.includes(r.slot));
  return (had ?? list[list.length - 1])?.id ?? "";
}

function useScanTable(run: string, scan: string, runs: TodayRuns | null, slots: string[]) {
  const id = tableRun(run, runs, slots);
  const [state, setState] = useState<{ key: string; table: ScanTable | null; error: string | null } | null>(null);
  const key = `${id}|${scan}`;
  useEffect(() => {
    if (!id) return;
    let live = true;
    api.scanTables(id, scan).then(
      (d) => live && setState({ key, table: d.scans[0] ?? null, error: null }),
      (e: Error) => live && setState({ key, table: null, error: e.message }),
    );
    return () => {
      live = false;
    };
  }, [id, scan, key]);
  return { id, state: state?.key === key ? state : null };
}

export function ScanTab({ run, scan, runs, slots }: { run: string; scan: string; runs: TodayRuns | null; slots: string[] }) {
  const { id, state } = useScanTable(run, scan, runs, slots);
  if (!id) return <p className="muted sc-pad">No run of today to read this scan from.</p>;
  if (!state) return <p className="muted sc-pad">Loading the scan&apos;s table…</p>;
  if (state.error) return <p className="error sc-pad">{state.error}</p>;
  if (!state.table) return <p className="muted sc-pad">That run has no hits for this scan.</p>;
  return (
    <div className="sc-pad">
      {run === ALL && <p className="muted">From the newest run of today with this scan.</p>}
      <ScanTableView run={id} table={state.table} />
    </div>
  );
}

/** The A+ / A / B blocks under the Scan hits table when one scan is picked. */
export function GradeBlocks({ run, scan, runs, slots }: { run: string; scan: string; runs: TodayRuns | null; slots: string[] }) {
  const { state } = useScanTable(run, scan, runs, slots);
  const blocks = state?.table?.blocks ?? [];
  if (!blocks.length) return null;
  return (
    <div className="grade-blocks sc-pad" aria-label="A+, A and B hits as the push shows them">
      {blocks.map((b) => (
        <div key={b.ticker} className="grade-block">
          <p>
            <b>{b.ticker}</b> · {blockLine(b.title)}
          </p>
          <ul>
            {b.lines.map((l, i) => (
              <li key={i}>{blockLine(l)}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
