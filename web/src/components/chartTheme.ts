// The charts' colours in the calm palette: the surface as background, hairline grid, green and
// red for price direction only, the moving average amber, the plan's lines labelled (entry in
// the accent, stop in caution amber, pivot neutral). Lines the API colours are mapped by name.
// No runtime import from lightweight-charts here (the page tests mock it): its enum values.
import type { ColorType, LineStyle } from "lightweight-charts";

const SOLID = 0 as LineStyle;
const DOTTED = 1 as LineStyle;
const DASHED = 2 as LineStyle;

export const T = {
  bg: "#11141a",
  grid: "#1c2028",
  border: "#23272f",
  text: "#98a2b3",
  up: "#2bc48a",
  down: "#f0616d",
  upFade: "#2bc48a40",
  downFade: "#f0616d40",
  accent: "#4c8dff",
  amber: "#f2a33a",
  ma: "#e2b04a",
  neutral: "#98a2b3",
};

export const LAYOUT = {
  layout: {
    background: { type: "solid" as ColorType.Solid, color: T.bg },
    textColor: T.text,
    fontFamily: '"Inter Variable", Inter, system-ui, sans-serif',
  },
  grid: { vertLines: { color: T.grid }, horzLines: { color: T.grid } },
  rightPriceScale: { borderColor: T.border },
  timeScale: { borderColor: T.border },
};

const LINES: Record<string, [string, LineStyle?]> = {
  "MA 10": [T.ma],
  "MA 20": ["#c9ced6"],
  "MA 50": ["#7d8696"],
  "MA 200": ["#5b6577"],
  "EMA 9": [T.ma, DASHED],
  "EMA 21": ["#c9ced6", DASHED],
  "AVWAP (signal day)": ["#8fb5ff", DOTTED],
  "RS vs QQQ": ["#98a2b3"],
};

/** A line's colour and style by its name ("MA 10" or "MA10"), else the API's colour. */
export function lineLook(name: string, fallback: string): { color: string; lineStyle: LineStyle } {
  const key = name.replace(/^(E?MA)(\d)/, "$1 $2");
  const hit = LINES[key];
  return { color: hit?.[0] ?? fallback, lineStyle: hit?.[1] ?? SOLID };
}

/** The plan's price lines: label and colour. */
export const LEVELS: Record<string, [string, string]> = {
  entry: ["Entry", T.accent],
  pivot: ["Pivot", T.neutral],
  stop: ["Stop", T.amber],
};
