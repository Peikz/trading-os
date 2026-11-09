// Grade badges and the key-fact strip, shared by Today, Stocks and the Journal. Badges: A+ solid
// accent, A accent tint, B neutral, C outlined, a watched stock amber, a position green.
import type { Stat } from "../api";
import { plain } from "../plain";
import { stockLink } from "../routes";

/** The full chart of a stock (Stocks, with drawing, AVWAPs, intraday and notes). */
export const chartLink = (ticker: string) => stockLink(ticker);

const GRADE_CLASS: Record<string, string> = {
  "A++": "g-aplus",
  "A+": "g-aplus",
  A: "g-a",
  B: "g-b",
  C: "g-c",
};

export function GradeBadge({ grade, large }: { grade: string; large?: boolean }) {
  return (
    <span className={`badge ${GRADE_CLASS[grade] ?? "g-c"}${large ? " lg" : ""}`} title={`Grade ${grade}`}>
      {grade}
    </span>
  );
}

export function KindBadge({ kind }: { kind: "watch" | "position" }) {
  return (
    <span className={`badge ${kind}`} title={kind === "watch" ? "On your watchlist" : "An open position"}>
      {kind === "watch" ? "Watch" : "Held"}
    </span>
  );
}

/** The quiet one-row strip of key facts under a chart, in plain words. */
const FIRST = ["Mkt cap", "ADR", "$ vol 20d", "Float", "RS", "Earnings"];
export function FactStrip({ stats, label = "Key facts" }: { stats: Stat[]; label?: string }) {
  const ordered = [
    ...FIRST.flatMap((k) => stats.filter((s) => s.label === k)),
    ...stats.filter((s) => !FIRST.includes(s.label)),
  ];
  if (!ordered.length) return null;
  return (
    <div className="strip" aria-label={label}>
      {ordered.map((s) => {
        const p = plain(s.label);
        return (
          <div key={s.label} title={p.title}>
            <span>{p.text}</span>
            <b className="num">{s.value}</b>
          </div>
        );
      })}
    </div>
  );
}
