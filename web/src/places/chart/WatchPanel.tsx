// The Chart's list panel. Desktop: a list picker on top, a filter box and a dense table (28 px rows,
// sticky header, sortable): symbol, grade chip, last, % change, 20-day sparkline, relative volume,
// setup; the active row has a 2 px accent bar. Each list remembers its sort and its columns.
// Phone: the same list as a bottom sheet (peek, half, full) with 44 px rows. Picking a row makes
// it the active stock.
import { type ReactNode, useEffect, useRef, useState } from "react";
import type { ChartListInfo, ChartListRow } from "../../api";
import { GradeBadge } from "../../components/Card";
import { nameOf, useNames } from "../../shell/symbols";
import { Icon } from "../../ui/Icon";
import { usePopover } from "../../ui/kit";
import { LIST_COLUMNS, type ListColumn, type Sort, type SortKey, useSparks } from "./lists";

const pct = (x: number | null) => (x === null ? "–" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}%`);
const price = (x: number | null) => (x === null ? "–" : x.toFixed(2));
const dir = (x: number | null) => (x === null ? "" : x >= 0 ? "up" : "down");

export function Sparkline({ closes }: { closes: number[] | undefined }) {
  if (!closes || closes.length < 2) return <span className="spark empty" aria-hidden="true" />;
  const lo = Math.min(...closes);
  const hi = Math.max(...closes);
  const w = 56;
  const h = 16;
  const span = hi - lo || 1;
  const pts = closes
    .map((c, i) => `${((i / (closes.length - 1)) * w).toFixed(1)},${(h - 1 - ((c - lo) / span) * (h - 2)).toFixed(1)}`)
    .join(" ");
  return (
    <svg className={`spark ${closes[closes.length - 1] >= closes[0] ? "up" : "down"}`} width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round" />
    </svg>
  );
}

function Grade({ grade }: { grade: string }) {
  return grade ? <GradeBadge grade={grade} /> : <span className="muted" aria-hidden="true">–</span>;
}

/** Scroll the active row into view when the stock changes (a key press, a click elsewhere). */
function useKeepInView(symbol: string) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const row = box.current?.querySelector('[data-active="true"]');
    if (row && "scrollIntoView" in row) (row as HTMLElement).scrollIntoView({ block: "nearest" });
  }, [symbol]);
  return box;
}

export function ListPicker({
  lists,
  value,
  onPick,
  fallback,
}: {
  lists: ChartListInfo[] | null;
  value: string;
  onPick: (id: string) => void;
  fallback: string;
}) {
  const groups = [...new Set((lists ?? []).map((l) => l.group))];
  return (
    <select aria-label="List" value={value} onChange={(e) => onPick(e.target.value)}>
      {!(lists ?? []).some((l) => l.id === value) && <option value={value}>{fallback}</option>}
      {groups.map((g) => (
        <optgroup key={g} label={g}>
          {(lists ?? [])
            .filter((l) => l.group === g)
            .map((l) => (
              <option key={l.id} value={l.id}>
                {l.label} ({l.count})
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  );
}

const COLUMNS: { key: SortKey | null; col: ListColumn | "ticker"; label: string; cls?: string }[] = [
  { key: "ticker", col: "ticker", label: "Symbol" },
  { key: "grade", col: "grade", label: "Gr", cls: "c" },
  { key: "last", col: "last", label: "Last", cls: "r" },
  { key: "chg_pct", col: "chg_pct", label: "%", cls: "r" },
  { key: null, col: "spark", label: "20d", cls: "c" },
  { key: "rvol", col: "rvol", label: "RVOL", cls: "r" },
  { key: "setup", col: "setup", label: "Setup" },
];

/** The filter box above a list: narrows the rows as you type (ticker, company name or setup). */
export function ListFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="list-filter">
      <Icon name="search" size={14} />
      <input
        aria-label="Filter this list"
        placeholder="Filter this list"
        autoComplete="off"
        spellCheck={false}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && value) {
            onChange("");
            e.stopPropagation();
          }
        }}
      />
      {value && (
        <button type="button" className="ghost icon-btn" aria-label="Clear the filter" onClick={() => onChange("")}>
          <Icon name="x" size={14} />
        </button>
      )}
    </label>
  );
}

/** Which columns the list shows (remembered per list). */
export function ColumnsMenu({ hidden, onToggle }: { hidden: ListColumn[]; onToggle: (c: ListColumn) => void }) {
  const { open, setOpen, ref } = usePopover();
  return (
    <div className="popover-wrap" ref={ref}>
      <button className="ghost icon-btn" aria-label="Columns" aria-expanded={open} title="Columns" onClick={() => setOpen(!open)}>
        <Icon name="sliders" size={16} />
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Columns">
          <h4>Columns in this list</h4>
          <div className="check-grid">
            {LIST_COLUMNS.map(([c, text]) => (
              <label key={c} className="check">
                <input type="checkbox" checked={!hidden.includes(c)} onChange={() => onToggle(c)} />
                {text}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function WatchTable({
  rows,
  symbol,
  onPick,
  sort,
  onSort,
  label,
  hidden = [],
  filtered = false,
}: {
  rows: ChartListRow[];
  symbol: string;
  onPick: (t: string) => void;
  sort: Sort | null;
  onSort: (key: SortKey) => void;
  label: string;
  hidden?: ListColumn[];
  filtered?: boolean;
}) {
  const sparks = useSparks(rows.map((r) => r.ticker));
  const box = useKeepInView(symbol);
  useNames();
  const shown = COLUMNS.filter((c) => c.col === "ticker" || !hidden.includes(c.col as ListColumn));
  const has = (c: ListColumn) => !hidden.includes(c);
  return (
    <div className="wl-scroll" ref={box}>
      <table className="wl" aria-label={`List: ${label}`}>
        <thead>
          <tr>
            {shown.map((c) => (
              <th
                key={c.label}
                className={`col-${c.col}${c.cls ? ` ${c.cls}` : ""}`}
                aria-sort={c.key && sort?.key === c.key ? (sort.down ? "descending" : "ascending") : undefined}
              >
                {c.key ? (
                  <button className="th-btn" onClick={() => onSort(c.key!)}>
                    {c.label}
                    {sort?.key === c.key && <Icon name={sort.down ? "down" : "up"} size={12} />}
                  </button>
                ) : (
                  c.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const active = r.ticker === symbol;
            const name = nameOf(r.ticker);
            return (
              <tr key={r.ticker} className={active ? "active" : undefined} data-active={active} onClick={() => onPick(r.ticker)}>
                <td title={name ? `${r.ticker} · ${name}` : undefined}>
                  <button className="wl-sym" aria-label={`Open ${r.ticker}`} aria-current={active ? "true" : undefined}>
                    {r.ticker}
                  </button>
                </td>
                {has("grade") && (
                  <td className="c">
                    <Grade grade={r.grade} />
                  </td>
                )}
                {has("last") && <td className="r num">{price(r.last)}</td>}
                {has("chg_pct") && <td className={`r num ${dir(r.chg_pct)}`}>{pct(r.chg_pct)}</td>}
                {has("spark") && (
                  <td className="c">
                    <Sparkline closes={sparks[r.ticker]} />
                  </td>
                )}
                {has("rvol") && <td className="r num">{r.rvol === null ? "–" : r.rvol.toFixed(1)}</td>}
                {has("setup") && (
                  <td className="setup" title={r.setup}>
                    {r.setup}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows.length === 0 && <p className="muted ws-empty">{filtered ? "No stock in this list matches." : "Nothing on this list."}</p>}
    </div>
  );
}

/** The phone's rows: grade, symbol, last, change and the sparkline on a 44 px row. */
export function PhoneList({
  rows,
  symbol,
  onPick,
  filtered = false,
}: {
  rows: ChartListRow[];
  symbol: string;
  onPick: (t: string) => void;
  filtered?: boolean;
}) {
  const sparks = useSparks(rows.map((r) => r.ticker));
  const box = useKeepInView(symbol);
  useNames();
  return (
    <div className="pl-scroll" ref={box}>
      <ul className="pl" aria-label="List">
        {rows.map((r) => {
          const active = r.ticker === symbol;
          const name = nameOf(r.ticker);
          return (
            <li key={r.ticker} data-active={active}>
              <button className={active ? "active" : undefined} aria-label={`Open ${r.ticker}`} onClick={() => onPick(r.ticker)}>
                <Grade grade={r.grade} />
                <span className="tk">
                  {r.ticker}
                  {name && <small className="muted co">{name}</small>}
                </span>
                <span className="num last">{price(r.last)}</span>
                <span className={`num chg ${dir(r.chg_pct)}`}>{pct(r.chg_pct)}</span>
                <Sparkline closes={sparks[r.ticker]} />
              </button>
            </li>
          );
        })}
      </ul>
      {rows.length === 0 && <p className="muted ws-empty">{filtered ? "No stock in this list matches." : "Nothing on this list."}</p>}
    </div>
  );
}

type Stop = "peek" | "half" | "full";
const STOPS: Stop[] = ["peek", "half", "full"];

/** A bottom sheet: tap or drag the handle to move between peek, half and full. */
export function Sheet({ title, children }: { title: ReactNode; children: ReactNode }) {
  const [stop, setStop] = useState<Stop>("peek");
  const start = useRef<number | null>(null);
  const move = (by: 1 | -1) =>
    setStop((s) => STOPS[Math.max(0, Math.min(STOPS.length - 1, STOPS.indexOf(s) + by))]);
  return (
    <section className={`sheet ${stop}`} aria-label="List sheet" data-stop={stop}>
      <button
        className="sheet-handle"
        aria-label={`List sheet: ${stop}. Tap or drag to change`}
        onPointerDown={(e) => {
          start.current = e.clientY;
        }}
        onPointerUp={(e) => {
          const from = start.current;
          start.current = null;
          if (from === null) return;
          const d = from - e.clientY;
          if (d > 24) move(1);
          else if (d < -24) move(-1);
          else setStop((s) => STOPS[(STOPS.indexOf(s) + 1) % STOPS.length]);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp") move(1);
          else if (e.key === "ArrowDown") move(-1);
          else return;
          e.preventDefault();
        }}
        // a keyboard activation has no pointer events: Enter and Space cycle
        onClick={(e) => {
          if (e.detail === 0) setStop((s) => STOPS[(STOPS.indexOf(s) + 1) % STOPS.length]);
        }}
      >
        <span className="grip" aria-hidden="true" />
        <span className="sheet-title">{title}</span>
      </button>
      <div className="sheet-body">{children}</div>
    </section>
  );
}
