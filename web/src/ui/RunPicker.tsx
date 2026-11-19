// The run picker (UX round 3): one chip per scan run of today (its name, how many stocks to act
// on it found, its time in New York and Copenhagen) and "All today". On a phone the chips are a
// row that scrolls sideways. The Screener's Scan hits page uses the same runs in a menu (RunMenu).
import type { TodayRuns } from "../api";
import { ALL, runTimes } from "../shell/todayRun";
import { usePopover } from "./kit";
import { Icon } from "./Icon";

export function RunPicker({ runs, value, onPick }: { runs: TodayRuns | null; value: string; onPick: (id: string) => void }) {
  if (!runs || runs.runs.length === 0) return null;
  const items = [
    { id: ALL, title: runs.all.label, count: runs.all.count, sub: runs.runs.length > 1 ? `${runs.runs.length} runs` : "" },
    ...runs.runs.map((r) => ({ id: r.id, title: r.name, count: r.count, sub: runTimes(r) })),
  ];
  return (
    <div className="run-picker" role="group" aria-label="Scan run">
      {items.map((i) => (
        <button key={i.id} type="button" className="run-chip" aria-pressed={value === i.id} onClick={() => onPick(i.id)}>
          <span className="run-top">
            <b>{i.title}</b>
            <span className="run-count num">{i.count}</span>
          </span>
          {i.sub && <span className="run-sub">{i.sub}</span>}
        </button>
      ))}
    </div>
  );
}

/** The same runs as a menu: "Run  All today (4) ▾" (the Screener's filter bar). */
export function RunMenu({
  runs,
  value,
  onPick,
  earlier = [],
}: {
  runs: TodayRuns | null;
  value: string;
  onPick: (id: string) => void;
  earlier?: { id: string; label: string }[];
}) {
  const { open, setOpen, ref } = usePopover();
  const current =
    value === ALL
      ? runs
        ? `${runs.all.label} (${runs.all.count})`
        : "All today"
      : (() => {
          const r = runs?.runs.find((x) => x.id === value);
          if (r) return `${r.name} (${r.count})`;
          return earlier.find((x) => x.id === value)?.label ?? value;
        })();
  const choose = (id: string) => {
    onPick(id);
    setOpen(false);
  };
  return (
    <div className="popover-wrap" ref={ref}>
      <button className="fbtn" aria-expanded={open} aria-haspopup="listbox" onClick={() => setOpen(!open)}>
        <span className="flabel">Run</span>
        {current}
        <Icon name="down" size={14} />
      </button>
      {open && (
        <div className="popover left menu" role="listbox" aria-label="Run">
          <button role="option" aria-selected={value === ALL} onClick={() => choose(ALL)}>
            <span>{runs?.all.label ?? "All today"}</span>
            <span className="muted num">{runs?.all.count ?? ""}</span>
          </button>
          {(runs?.runs ?? []).map((r) => (
            <button key={r.id} role="option" aria-selected={value === r.id} onClick={() => choose(r.id)}>
              <span>
                {r.name}
                <small className="muted"> {runTimes(r)}</small>
              </span>
              <span className="muted num">{r.count}</span>
            </button>
          ))}
          {earlier.length > 0 && <div className="menu-label">Earlier runs</div>}
          {earlier.map((r) => (
            <button key={r.id} role="option" aria-selected={value === r.id} onClick={() => choose(r.id)}>
              <span>{r.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
