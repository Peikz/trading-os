// The run picker (UX round 3): one chip per scan run of today (its name, how many stocks to act
// on it found, its time in New York and Copenhagen) and "All today". On a phone the chips are a
// row that scrolls sideways. The Screener's Scan hits page uses the same runs in a menu (RunMenu).
import type { TodayRuns } from "../api";
import { ALL, runTimes } from "../shell/todayRun";
import { usePopover } from "./kit";
import { Icon } from "./Icon";

export function RunPicker({
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
  if (!runs || (runs.runs.length === 0 && earlier.length === 0)) return null;
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
      {earlier.length > 0 && <EarlierChip earlier={earlier} value={value} onPick={onPick} />}
    </div>
  );
}

/** "Earlier ▾": a chip that opens the runs of earlier days; pressed while one of them is picked. */
function EarlierChip({ earlier, value, onPick }: { earlier: { id: string; label: string }[]; value: string; onPick: (id: string) => void }) {
  const { open, setOpen, ref } = usePopover();
  const picked = earlier.find((e) => e.id === value);
  return (
    <div className="popover-wrap" ref={ref}>
      <button type="button" className="run-chip" aria-pressed={!!picked} aria-expanded={open} aria-haspopup="listbox" onClick={() => setOpen(!open)}>
        <span className="run-top">
          <b>{picked ? "Earlier run" : "Earlier"}</b>
          <Icon name="down" size={14} />
        </span>
        {picked && <span className="run-sub">{picked.label}</span>}
      </button>
      {open && (
        <div className="popover left menu" role="listbox" aria-label="Earlier runs">
          {earlier.map((r) => (
            <button
              key={r.id}
              role="option"
              aria-selected={value === r.id}
              onClick={() => {
                onPick(r.id);
                setOpen(false);
              }}
            >
              <span>{r.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** The same runs as a menu: "Run  All today (4) ▾" (the Screener's filter bar). */
export function RunMenu({
  runs,
  value,
  onPick,
  earlier = [],
  noAll,
}: {
  runs: TodayRuns | null;
  value: string;
  onPick: (id: string) => void;
  earlier?: { id: string; label: string }[];
  /** Leave out "All today" (a table is one run's) */
  noAll?: boolean;
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
          {!noAll && (
            <button role="option" aria-selected={value === ALL} onClick={() => choose(ALL)}>
              <span>{runs?.all.label ?? "All today"}</span>
              <span className="muted num">{runs?.all.count ?? ""}</span>
            </button>
          )}
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
