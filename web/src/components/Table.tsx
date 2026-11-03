// A plain table of API rows (Journal, Watchlists, Plans). Values are shown as the API sends
// them, formatted per column (`cell`); nothing is computed here.
import type { ReactNode } from "react";
import type { ApiTable, Row, Value } from "../api";
import { cell } from "../format";
import { plain } from "../plain";

export function Table({
  columns,
  rows,
  label,
  render,
}: {
  columns: string[];
  rows: Row[];
  label: string;
  render?: (column: string, row: Row) => ReactNode | undefined;
}) {
  if (!rows.length) return null;
  return (
    <div className="table-wrap">
      <table aria-label={label}>
        <thead>
          <tr>
            {columns.map((c) => {
              const p = plain(c);
              return (
                <th key={c} title={p.title}>
                  {p.text}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c}>{render?.(c, r) ?? cell(c, r[c] as Value)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A line with **bold** parts, as the package writes them (the watchlist add feedback). */
export function Marked({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return <>{parts.map((p, i) => (i % 2 ? <b key={i}>{p}</b> : p))}</>;
}

/** An API table ({columns, rows, total}), with a note when only the first rows came. */
export function ApiTableView({
  table,
  label,
  empty,
}: {
  table: ApiTable | null | undefined;
  label: string;
  empty?: string;
}) {
  if (!table || !table.rows.length) return empty ? <p className="muted">{empty}</p> : null;
  return (
    <>
      <Table label={label} columns={table.columns} rows={table.rows} />
      {table.total > table.rows.length && (
        <p className="muted">
          The first {table.rows.length} of {table.total}.
        </p>
      )}
    </>
  );
}

/** One section at a time (Research, Live results, System health), like Streamlit's radio. */
export function Sections<T extends string>({
  label,
  options,
  value,
  onPick,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onPick: (v: T) => void;
}) {
  return (
    <div className="tabs small" role="tablist" aria-label={label}>
      {options.map((o) => (
        <button key={o} role="tab" aria-selected={value === o} className={value === o ? "on" : ""} onClick={() => onPick(o)}>
          {o}
        </button>
      ))}
    </div>
  );
}

/** A labelled number, like Streamlit's metric: label, value, an optional delta under it. */
export function Metric({ label, value, delta }: { label: string; value: string; delta?: string }) {
  return (
    <div className="metric">
      <span className="muted">{label}</span>
      <b>{value}</b>
      {delta && <span className="muted">{delta}</span>}
    </div>
  );
}
