// "All scans" on the Scan hits page lists a stock once, however many scans found it: the best
// grade's row (the API sends the hits best first), its setups joined ("EP 10:30 · EP9M pace") and
// every run it was a hit in, in the order the runs happen. A single scan keeps its own rows.
import type { ScanHit } from "../../api";

const SLOTS = ["pm", "am", "mid", "eod", "ah"];
const order = (a: string, b: string) => (SLOTS.indexOf(a) + 1 || 99) - (SLOTS.indexOf(b) + 1 || 99);

export function onePerStock(rows: ScanHit[]): ScanHit[] {
  const by = new Map<string, ScanHit & { setups: string[] }>();
  for (const r of rows) {
    const t = String(r.ticker);
    const found = by.get(t);
    if (!found) {
      by.set(t, { ...r, setups: [r.scan_label], runs: [...(r.runs ?? [])] });
      continue;
    }
    if (!found.setups.includes(r.scan_label)) found.setups.push(r.scan_label);
    for (const run of r.runs ?? []) if (!found.runs.includes(run)) found.runs.push(run);
  }
  return [...by.values()].map(({ setups, ...r }) => ({
    ...r,
    scan_label: setups.join(" · "),
    runs: [...r.runs].sort(order),
  }));
}
