// A plain table of API rows (Journal, Watchlists, Plans). Values are shown as the API sends
// them, formatted per column (`cell`); nothing is computed here.
import type { ReactNode } from "react";
import type { Row, Value } from "../api";
import { cell } from "../format";

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
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
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
