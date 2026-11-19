// A plain table of API rows (Journal, Watchlists, Plans). Values are shown as the API sends
// them, formatted per column (`cell`); nothing is computed here. Every table sorts by a click on a
// header (a second click flips it, a third clears it) and downloads as a CSV (round 4).
import { type ReactNode, useMemo, useState } from "react";
import type { ApiTable, Row, Value } from "../api";
import { cell, download } from "../format";
import { plain } from "../plain";
import { hasMarks, IconText } from "./IconText";

const marked = (text: string) => (hasMarks(text) ? <IconText text={text} /> : text);

/** Rows in the order of a clicked header: numbers by value, words A to Z, blanks last. */
export function sortedRows<T extends Record<string, unknown>>(rows: T[], sort: { col: string; down: boolean } | null): T[] {
  if (!sort) return rows;
  const val = (r: T): number | string | null => {
    const v = r[sort.col];
    if (v === null || v === undefined || v === "") return null;
    if (typeof v === "boolean") return Number(v);
    return typeof v === "number" ? v : String(v);
  };
  return [...rows].sort((a, b) => {
    const x = val(a);
    const y = val(b);
    if (x === null && y === null) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true });
    return sort.down ? -c : c;
  });
}

/** A table as CSV text: the header's words, then each row's raw values. */
export function tableCsv(columns: string[], rows: Row[], headers: Record<string, string> = {}): string {
  const q = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const real = columns.filter((c) => c.trim() !== "");
  return [real.map((c) => q(headers[c] ?? plain(c).text)).join(","), ...rows.map((r) => real.map((c) => q(r[c])).join(","))].join("\n");
}

export function Table({
  columns,
  rows,
  label,
  render,
  headers = {},
  onRow,
}: {
  columns: string[];
  rows: Row[];
  label: string;
  render?: (column: string, row: Row) => ReactNode | undefined;
  /** Header words where the column key is not plain English (the scans' own columns) */
  headers?: Record<string, string>;
  /** A click (or Enter) on a row, for a table that opens something */
  onRow?: (row: Row) => void;
}) {
  const [sort, setSort] = useState<{ col: string; down: boolean } | null>(null);
  const shown = useMemo(() => sortedRows(rows, sort), [rows, sort]);
  if (!rows.length) return null;
  const click = (c: string) => setSort((s) => (!s || s.col !== c ? { col: c, down: false } : s.down ? null : { col: c, down: true }));
  return (
    <>
      <div className="table-tools">
        <button
          type="button"
          className="ghost table-csv"
          aria-label={`Download ${label} as CSV`}
          onClick={() => download(`${label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "table"}.csv`, tableCsv(columns, rows, headers))}
        >
          CSV
        </button>
      </div>
      <div className="table-wrap">
        <table aria-label={label}>
          <thead>
            <tr>
              {columns.map((c) => {
                const p = headers[c] ? { text: headers[c], title: undefined } : plain(c);
                const on = sort?.col === c;
                return (
                  <th key={c} title={p.title} aria-sort={on ? (sort.down ? "descending" : "ascending") : undefined}>
                    {c.trim() === "" ? null : (
                      <button type="button" className="th-sort" onClick={() => click(c)}>
                        {p.text}
                        {on && <span aria-hidden="true">{sort.down ? " ▾" : " ▴"}</span>}
                      </button>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr
                key={i}
                className={onRow ? "clickable" : undefined}
                tabIndex={onRow ? 0 : undefined}
                onClick={onRow ? () => onRow(r) : undefined}
                onKeyDown={onRow ? (e) => e.key === "Enter" && onRow(r) : undefined}
              >
                {columns.map((c) => (
                  <td key={c}>{render?.(c, r) ?? marked(cell(c, r[c] as Value))}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
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
