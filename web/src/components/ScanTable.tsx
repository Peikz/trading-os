// One pushed scan's table of one run, as the push and the Markdown report show it (round 4,
// Streamlit's "All scans" and a scan's own table in the Screener): the scan's own columns, the
// study grade, why, predicted R, short interest, the IBD tag, the volume build and a TradingView
// link; then the A+ / A / B blocks (when to buy, the exit, the history behind the grade, the
// plan, the Saxo ticket), the facts behind the names and the push's saved chart images.
// Every number is formatted from what the API sent; nothing is computed here.
import { api, type ScanTable, type Value } from "../api";
import { compact } from "../format";
import { stripIcons } from "../plain";
import { GradeBadge } from "./Card";
import { Markdown } from "./Markdown";
import { Table } from "./Table";

const fixed = (n: number, d: number) => n.toFixed(d);
const signed = (n: number, d: number) => `${n >= 0 ? "+" : ""}${n.toFixed(d)}`;

/** A cell of a scan table: the report's number formats (int, +.1f, money, shares ...). */
export function scanCell(fmt: string, v: Value | undefined) {
  if (v === null || v === undefined || v === "") return "–";
  if (fmt === "link") return typeof v === "string" ? <a href={v} target="_blank" rel="noreferrer">TradingView ↗</a> : "–";
  if (fmt === "flag") return v ? "yes" : "no";
  if (typeof v !== "number") return String(v);
  switch (fmt) {
    case "int":
      return Math.round(v).toLocaleString("en-US");
    case "money":
      return `$${compact(v)}`;
    case "shares":
      return compact(v);
    case "num0":
      return fixed(v, 0);
    case "num1":
      return fixed(v, 1);
    case "num2":
      return fixed(v, 2);
    case "signed0":
      return signed(v, 0);
    case "signed1":
      return signed(v, 1);
    case "signed2":
      return signed(v, 2);
    default:
      return String(v);
  }
}

/** A line of a push block without its pictographs: the stop sign becomes the word. */
export const blockLine = (l: string) => stripIcons(l.replace(/🛑\s*/gu, "stop ")).trim();

export function ScanTableView({ run, table, only }: { run: string; table: ScanTable; only?: string[] }) {
  const fmt = Object.fromEntries(table.columns.map((c) => [c.key, c.fmt]));
  const headers = Object.fromEntries(table.columns.map((c) => [c.key, c.header]));
  const keep = (t: string) => !only || only.includes(t);
  const blocks = table.blocks.filter((b) => keep(b.ticker));
  return (
    <section className="scan-table" aria-label={`${table.label} table`}>
      <h3>
        {table.label} <span className="muted">· {table.shown} of {table.total} hits</span>
      </h3>
      <Table
        label={`${table.label} hits`}
        columns={table.columns.map((c) => c.key)}
        headers={headers}
        rows={table.rows}
        render={(c, r) =>
          c === "grade" && typeof r.grade === "string" && r.grade ? (
            <GradeBadge grade={r.grade} />
          ) : (
            scanCell(fmt[c], r[c] as Value)
          )
        }
      />
      {blocks.length > 0 && (
        <div className="grade-blocks" aria-label={`${table.label}: A+, A and B hits as the push shows them`}>
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
      )}
      {table.facts.length > 0 && <Markdown text={table.facts.join("\n")} />}
      {table.charts.length > 0 && (
        <div className="scan-charts" aria-label={`${table.label}: the push's chart images`}>
          {table.charts.map((t) => (
            <figure key={t}>
              <img src={api.runChartUrl(run, table.scan, t)} alt={`${t} chart`} loading="lazy" />
              <figcaption>{t}</figcaption>
            </figure>
          ))}
        </div>
      )}
    </section>
  );
}
