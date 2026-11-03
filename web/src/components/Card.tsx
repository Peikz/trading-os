// One candidate's card: the grade, the setup and run, then its facts (when to buy, entry,
// stop, shares, risk, tags, history, why). All lines come from the API (trading_os.board_data).
import type { BoardRow } from "../api";
import { GRADE_COLOURS } from "../format";

export function GradeBadge({ grade }: { grade: string }) {
  return (
    <span className="badge" style={{ background: GRADE_COLOURS[grade] ?? "#6e7781" }}>
      {grade}
    </span>
  );
}

export function Card({ row }: { row: BoardRow }) {
  return (
    <article className="card" aria-label={`${row.ticker} card`}>
      <header>
        <GradeBadge grade={row.grade} /> <b className="ticker">{row.ticker}</b> · {row.scan_label}{" "}
        <span className="muted">{row.run_label}</span>
      </header>
      {row.facts.length > 0 ? (
        <ul>
          {row.facts.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">No plan for this signal.</p>
      )}
    </article>
  );
}

export function KeyStats({ row }: { row: BoardRow }) {
  return (
    <div className="chips" aria-label="Key stats">
      {row.stats.map((s) => (
        <span className="chip" key={s.label}>
          <span className="muted">{s.label}</span> <b>{s.value}</b>
        </span>
      ))}
    </div>
  );
}

export function Queue({
  rows,
  index,
  onPick,
}: {
  rows: BoardRow[];
  index: number;
  onPick: (i: number) => void;
}) {
  return (
    <ol className="queue">
      {rows.map((r, k) => (
        <li key={`${r.ticker}-${r.scan}`}>
          <button className={k === index ? "active" : ""} onClick={() => onPick(k)}>
            {r.grade} · {r.ticker} · {r.scan_label}
            {typeof r.chg_pct === "number" && (
              <span className="muted">
                {" "}
                {r.chg_pct >= 0 ? "+" : ""}
                {r.chg_pct.toFixed(1)}%
              </span>
            )}
          </button>
        </li>
      ))}
    </ol>
  );
}
