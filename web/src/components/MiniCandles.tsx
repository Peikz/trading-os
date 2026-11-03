// A small candle chart drawn as SVG (the Stocks grid and the phone card): no axes, no
// interaction, one element per candle, so a grid of thirty stays light.
import type { Spark } from "../api";

export function MiniCandles({
  candles,
  height = 96,
  width = 300,
  levels,
  label,
}: {
  candles: Spark;
  height?: number;
  width?: number;
  levels?: Record<string, number>;
  label: string;
}) {
  if (!candles.length) {
    return (
      <svg className="mini" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}: no bars`}>
        <text x={width / 2} y={height / 2} textAnchor="middle" fill="#98a2b3" fontSize="12">
          No bars
        </text>
      </svg>
    );
  }
  const lv = Object.values(levels ?? {});
  const hi = Math.max(...candles.map((c) => c.high), ...lv);
  const lo = Math.min(...candles.map((c) => c.low), ...lv);
  const pad = 4;
  const y = (p: number) => pad + ((hi - p) / (hi - lo || 1)) * (height - 2 * pad);
  const step = width / candles.length;
  const body = Math.max(1, step * 0.6);
  return (
    <svg className="mini" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={`${label}: last ${candles.length} days`}>
      {Object.entries(levels ?? {}).map(([name, p]) => (
        <line
          key={name}
          x1={0}
          x2={width}
          y1={y(p)}
          y2={y(p)}
          stroke={name === "stop" ? "#f2a33a" : name === "entry" ? "#4c8dff" : "#98a2b3"}
          strokeDasharray="4 3"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {candles.map((c, i) => {
        const up = c.close >= c.open;
        const colour = up ? "#2bc48a" : "#f0616d";
        const x = i * step + step / 2;
        const top = y(Math.max(c.open, c.close));
        return (
          <g key={c.time}>
            <line x1={x} x2={x} y1={y(c.high)} y2={y(c.low)} stroke={colour} strokeWidth={1} vectorEffect="non-scaling-stroke" />
            <rect x={x - body / 2} y={top} width={body} height={Math.max(1, y(Math.min(c.open, c.close)) - top)} fill={colour} />
          </g>
        );
      })}
    </svg>
  );
}
