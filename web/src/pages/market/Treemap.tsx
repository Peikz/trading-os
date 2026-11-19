// The sector heatmap (UX round 3, Finviz / Koyfin): a treemap with one tile per sector, index and
// theme, equal in size (the data has no market caps for them), coloured by the % change over the
// chosen period from red through grey to green. Click a sector to filter the Screener to it.
import { go } from "../../routes";

export interface TreeItem {
  key: string;
  name: string;
  ticker: string;
  group: string;
  value: number | null;
}
interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Squarified layout of equal-weight items into a 0-100 by 0-100 box. */
export function layout(count: number, box: Rect = { x: 0, y: 0, w: 100, h: 100 }): Rect[] {
  const out: Rect[] = [];
  let rest = count;
  let area = { ...box };
  while (rest > 0) {
    // Lay a row along the short side, as many items as keep the tiles close to square
    const vertical = area.w >= area.h; // the row is a column down the left when the box is wide
    const side = vertical ? area.h : area.w;
    const unit = (area.w * area.h) / rest; // the area of one item
    let n = 1;
    let best = Infinity;
    for (let k = 1; k <= rest; k++) {
      const thickness = (k * unit) / side;
      const long = side / k;
      const worst = Math.max(thickness / long, long / thickness);
      if (worst > best) break;
      best = worst;
      n = k;
    }
    const thickness = (n * unit) / side;
    for (let i = 0; i < n; i++) {
      out.push(
        vertical
          ? { x: area.x, y: area.y + (i * side) / n, w: thickness, h: side / n }
          : { x: area.x + (i * side) / n, y: area.y, w: side / n, h: thickness },
      );
    }
    area = vertical
      ? { x: area.x + thickness, y: area.y, w: area.w - thickness, h: area.h }
      : { x: area.x, y: area.y + thickness, w: area.w, h: area.h - thickness };
    rest -= n;
  }
  return out;
}

const GREY: [number, number, number] = [42, 48, 58];
const GREEN: [number, number, number] = [38, 166, 154];
const RED: [number, number, number] = [239, 83, 80];

/** Diverging colour: grey at 0, full green or red at `scale`. */
export function heat(value: number | null, scale: number): string {
  if (value === null) return `rgb(${GREY.join(",")})`;
  const t = Math.min(1, Math.abs(value) / scale) * 0.85;
  const end = value >= 0 ? GREEN : RED;
  return `rgb(${GREY.map((g, i) => Math.round(g + (end[i] - g) * t)).join(",")})`;
}

/** The universe's own sector names for each sector ETF's name (the Screener filters on these). */
export const SCREENER_SECTORS: Record<string, string[]> = {
  Technology: ["Electronic Technology", "Technology Services"],
  Communication: ["Communications"],
  "Consumer discretionary": ["Consumer Durables", "Consumer Services", "Retail Trade"],
  Financials: ["Finance"],
  Industrials: ["Industrial Services", "Producer Manufacturing", "Transportation", "Commercial Services"],
  "Health care": ["Health Technology", "Health Services"],
  Energy: ["Energy Minerals"],
  Materials: ["Non-Energy Minerals", "Process Industries"],
  "Consumer staples": ["Consumer Non-Durables", "Distribution Services"],
  Utilities: ["Utilities"],
};

export function Treemap({ items, period, scale }: { items: TreeItem[]; period: string; scale: number }) {
  const rects = layout(items.length);
  return (
    <div className="treemap" role="list" aria-label={`Sectors by change, ${period}`}>
      {items.map((it, i) => {
        const r = rects[i];
        const filter = it.group === "Sector" ? SCREENER_SECTORS[it.name] : undefined;
        const text = it.value === null ? "–" : `${it.value >= 0 ? "+" : ""}${it.value.toFixed(1)}%`;
        return (
          <button
            key={it.key}
            role="listitem"
            className="tm-tile"
            style={{ left: `${r.x}%`, top: `${r.y}%`, width: `${r.w}%`, height: `${r.h}%`, background: heat(it.value, scale) }}
            disabled={!filter}
            title={filter ? `${it.name} ${text}: show these stocks in the Screener` : `${it.name} (${it.ticker}) ${text}`}
            aria-label={`${it.name} ${text}${filter ? ", open in the Screener" : ""}`}
            onClick={() => filter && go("screener", "screen", { sector: filter.join(",") })}
          >
            <span className="tm-name">{it.name}</span>
            <b className="num">{text}</b>
            <span className="tm-group">{it.group}</span>
          </button>
        );
      })}
    </div>
  );
}
