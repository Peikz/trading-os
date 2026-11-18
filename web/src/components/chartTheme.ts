// The charts' colours (the spec's tokens): the panel as background, hairline grid, green and
// red for price direction only, the moving average amber, the plan's lines labelled (entry in
// the accent, stop in caution amber, pivot neutral). Lines the API colours are mapped by name.
// No runtime import from lightweight-charts here (the page tests mock it): its enum values.
import type { ColorType, LineStyle } from "lightweight-charts";

const SOLID = 0 as LineStyle;
const DOTTED = 1 as LineStyle;
const DASHED = 2 as LineStyle;

export const T = {
  bg: "#12161c",
  grid: "#1e2632",
  border: "#232a35",
  text: "#9aa4b5",
  up: "#26a69a",
  down: "#ef5350",
  upFade: "#26a69a66", // volume at 40 % opacity
  downFade: "#ef535066",
  accent: "#4c8dff",
  amber: "#f5a524",
  ma: "#f5a524",
  neutral: "#9aa4b5",
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
  "MA 20": ["#c9d1dc"],
  "MA 50": ["#8f9bb0"],
  "MA 200": ["#657084"],
  "EMA 9": [T.ma, DASHED],
  "EMA 21": ["#c9d1dc", DASHED],
  "AVWAP (signal day)": [T.accent, DOTTED],
  "RS vs QQQ": [T.neutral],
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
