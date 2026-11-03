// Market (trading_os/market_view.py): the market as tiles, the IBD state's last 30 sessions,
// the setups at today's heat (or any other), indexes / sectors / themes with their rotation
// against SPY, the industries' rank moves, and the breadth history with the Market Light.
// Facts about past rules, not advice.
import { ColorType, createChart, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { api, type MarketPage } from "../api";
import { deltaColour } from "../format";
import { ApiTableView } from "../components/Table";

export function Market() {
  const [p, setP] = useState<Record<string, string>>({});
  const [data, setData] = useState<MarketPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify(p);
  useEffect(() => {
    let live = true;
    api.marketPage(JSON.parse(key)).then(
      (d) => live && setData(d),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [key]);
  if (!data) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;
  if (data.empty) {
    return (
      <div>
        <h2>Market</h2>
        <p className="muted">Breadth rows start with the first scheduled EOD run.</p>
      </div>
    );
  }
  const set = (k: string, v: string) => setP({ ...p, [k]: v });
  const picked = data.picked!;
  const heat = data.heat;
  return (
    <div>
      <h2>Market</h2>
      <div className="metrics">
        {data.tiles!.map((t) => (
          <div className="metric" key={t.label}>
            <span className="muted">{t.label}</span>
            <b>{t.value}</b>
            {t.delta && <span style={{ color: deltaColour(t.label, t.delta) }}>{t.delta}</span>}
          </div>
        ))}
      </div>
      <details>
        <summary>The IBD market state (tracked, not a rule)</summary>
        <ApiTableView
          label="IBD market state"
          table={data.ibd}
          empty="Needs SPY's daily bars (data/market/spy_daily_seed.parquet)."
        />
        <p className="muted">{data.ibd_caption}</p>
      </details>
      {heat && (
        <section>
          <h3>
            {heat.now[0].toUpperCase() + heat.now.slice(1)} market: scan count {heat.count} (
            {heat.bands.find((b) => b.band === heat.now)?.label})
          </h3>
          <div className="pills wrap" role="group" aria-label="Setups at this heat">
            {heat.bands.map((b) => (
              <button key={b.band} className={heat.band === b.band ? "on" : ""} onClick={() => set("band", b.band)}>
                {b.band} ({b.label})
              </button>
            ))}
          </div>
          <ApiTableView label="Setups at this heat" table={heat.table} />
          <p className="muted">{heat.caption}</p>
        </section>
      )}
      <h3>Indexes, sectors and themes</h3>
      {data.sectors ? (
        <>
          <div className="row">
            <div className="pills wrap" role="group" aria-label="Return over">
              {data.periods!.map((x) => (
                <button key={x} className={data.period === x ? "on" : ""} onClick={() => set("period", x)}>
                  {x}
                </button>
              ))}
            </div>
            <div className="pills" role="group" aria-label="Show">
              {data.groups!.map((g) => (
                <button
                  key={g}
                  className={picked.includes(g) ? "on" : ""}
                  onClick={() =>
                    set("groups", (picked.includes(g) ? picked.filter((x) => x !== g) : [...picked, g]).join(","))
                  }
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
          <ApiTableView label="Indexes, sectors and themes" table={data.sectors} />
          <p className="muted">{data.sector_caption}</p>
          <Rotation points={data.rotation!} />
        </>
      ) : (
        <p className="muted">No sector data yet: it comes from TradingView, and with each EOD run.</p>
      )}
      {data.industries && (
        <section>
          <h3>Industries: who leads and who is moving</h3>
          <div className="pills" role="group" aria-label="Rank move since">
            {["1 week", "1 month"].map((x) => (
              <button key={x} className={data.back === x ? "on" : ""} onClick={() => set("back", x)}>
                {x}
              </button>
            ))}
          </div>
          <div className="two">
            <div>
              <b>Top 15 now</b>
              <ApiTableView label="Top 15 industries" table={data.industries.top} />
            </div>
            <div>
              <b>Climbing most ({data.back})</b>
              <ApiTableView label="Climbing most" table={data.industries.climbing} />
            </div>
          </div>
          <p className="muted">{data.industries.caption}</p>
        </section>
      )}
      <h3>Breadth and the Market Light</h3>
      <div className="scroll-box">
        <ApiTableView label="Breadth" table={data.breadth} />
      </div>
      <Ratios points={data.ratios!} />
    </div>
  );
}

const GROUP_COLOURS: Record<string, string> = { Index: "#2f81f7", Sector: "#3fb950", Theme: "#d29922" };

/** The rotation chart: 1 month vs SPY across, 1 week vs SPY up, the four quadrants named. */
export function Rotation({ points }: { points: { ticker: string; group: string; x: number; y: number }[] }) {
  if (!points.length) return null;
  const w = 640;
  const h = 420;
  const pad = 36;
  const span = Math.max(1, ...points.flatMap((p) => [Math.abs(p.x), Math.abs(p.y)])) * 1.15;
  const sx = (x: number) => pad + ((x + span) / (2 * span)) * (w - 2 * pad);
  const sy = (y: number) => h - pad - ((y + span) / (2 * span)) * (h - 2 * pad);
  const corner = [
    ["Improving", pad + 6, pad + 14, "start"],
    ["Leading", w - pad - 6, pad + 14, "end"],
    ["Lagging", pad + 6, h - pad - 8, "start"],
    ["Weakening", w - pad - 6, h - pad - 8, "end"],
  ] as const;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="rotation" role="img" aria-label="Rotation against SPY">
      <line x1={sx(0)} y1={pad} x2={sx(0)} y2={h - pad} stroke="#555" />
      <line x1={pad} y1={sy(0)} x2={w - pad} y2={sy(0)} stroke="#555" />
      {corner.map(([t, x, y, a]) => (
        <text key={t} x={x} y={y} textAnchor={a} fill="#777" fontSize="12">
          {t}
        </text>
      ))}
      <text x={w / 2} y={h - 8} textAnchor="middle" fill="#8b949e" fontSize="11">
        1 month vs SPY (%)
      </text>
      <text x={12} y={h / 2} textAnchor="middle" fill="#8b949e" fontSize="11" transform={`rotate(-90 12 ${h / 2})`}>
        1 week vs SPY (%)
      </text>
      {points.map((p) => (
        <g key={p.ticker}>
          <circle cx={sx(p.x)} cy={sy(p.y)} r={4} fill={GROUP_COLOURS[p.group] ?? "#8b949e"} />
          <text x={sx(p.x)} y={sy(p.y) - 7} textAnchor="middle" fill="#d1d4dc" fontSize="10">
            {p.ticker}
          </text>
        </g>
      ))}
    </svg>
  );
}

function Ratios({ points }: { points: { time: string; ratio_5d: number | null; ratio_10d: number | null }[] }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current || !points.length) return;
    const c = createChart(box.current, {
      height: 220,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0e1117" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#1f242c" }, horzLines: { color: "#1f242c" } },
    });
    for (const [k, colour] of [["ratio_5d", "#2f81f7"], ["ratio_10d", "#d29922"]] as const) {
      const s = c.addLineSeries({ color: colour, lineWidth: 2, title: k, priceLineVisible: false });
      s.setData(
        points.filter((p) => p[k] !== null).map((p) => ({ time: p.time as Time, value: p[k] as number })),
      );
    }
    c.timeScale().fitContent();
    return () => c.remove();
  }, [points]);
  return <div ref={box} className="chart" style={{ height: 220 }} aria-label="Breadth ratios" />;
}
