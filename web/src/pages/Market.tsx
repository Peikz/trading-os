// Market (trading_os/market_view.py), one tab at a time: Overview (the tiles, the market in one
// word with its reasons, the push's market lines), Heat & setups (the setups at today's heat or
// any other), Sectors (indexes / sectors / themes with their rotation against SPY, and the
// industries' rank moves), Breadth (the history with the Market Light) and IBD (the state's
// last 30 sessions). Facts about past rules, not advice.
import { createChart, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { api, type Market as MarketTiles, type MarketPage } from "../api";
import { deltaColour } from "../format";
import { IconText } from "../components/IconText";
import { plain, stripIcons } from "../plain";
import { ApiTableView } from "../components/Table";
import { LAYOUT, T } from "../components/chartTheme";

export function Market({ tab = "overview" }: { tab?: string }) {
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
    return <p className="muted">Breadth rows start with the first scheduled EOD run.</p>;
  }
  const set = (k: string, v: string) => setP({ ...p, [k]: v });
  const picked = data.picked!;
  const heat = data.heat;
  return (
    <div>
      {tab === "overview" && (
        <>
          <div className="metrics">
            {data.tiles!.map((t) => (
              <div className="metric" key={t.label}>
                <span className="muted">{plain(t.label).text}</span>
                <b className="num">{stripIcons(t.value)}</b>
                {t.delta && (
                  <span className="num" style={{ color: deltaColour(t.label, t.delta) }}>
                    {t.delta}
                  </span>
                )}
              </div>
            ))}
          </div>
          <Overview />
        </>
      )}
      {tab === "ibd" && (
        <section>
          <p className="muted">The IBD market state over the last 30 sessions (tracked, not a rule).</p>
          <ApiTableView
            label="IBD market state"
            table={data.ibd}
            empty="Needs SPY's daily bars (data/market/spy_daily_seed.parquet)."
          />
          <p className="muted">{data.ibd_caption}</p>
        </section>
      )}
      {tab === "heat" &&
        (heat ? (
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
        ) : (
          <p className="muted">No heat statistics yet (data/grading/heat_stats.json).</p>
        ))}
      {tab === "sectors" && (
        <>
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
        </>
      )}
      {tab === "breadth" && (
        <>
          <h3>Breadth and the Market Light</h3>
          <Ratios points={data.ratios!} />
          <div className="scroll-box" style={{ marginTop: 16 }}>
            <ApiTableView label="Breadth" table={data.breadth} />
          </div>
        </>
      )}
    </div>
  );
}

/** The market in one word with its three reasons, and the push's market lines. */
function Overview() {
  const [m, setM] = useState<MarketTiles | null>(null);
  useEffect(() => {
    api.market().then(setM, () => setM(null));
  }, []);
  if (!m) return null;
  return (
    <div className="two">
      <section className="card">
        <h3>
          <span className={`dot ${m.mood?.level ?? ""}`} aria-hidden="true" /> {m.mood?.word ?? "No market data"}
        </h3>
        <ul className="reasons-list">
          {(m.mood?.reasons ?? []).map((r) => (
            <li key={r.text}>
              <span className={`dot ${r.level}`} aria-hidden="true" /> {r.text}
            </li>
          ))}
        </ul>
        <p className="muted hint">
          Healthy when QQQ light, heat and IBD are all green, weak when two are red, cautious
          otherwise. A summary of facts, not a rule.
        </p>
      </section>
      <section className="card">
        <h3>The push's market lines</h3>
        {m.details.length ? (
          <ul className="details">
            {m.details.map((line) => (
              <li key={line}>
                <IconText text={line} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No market lines yet.</p>
        )}
      </section>
    </div>
  );
}

// Index, sector, theme: three neutral hues (green and red are kept for price direction)
const GROUP_COLOURS: Record<string, string> = { Index: "#8fb5ff", Sector: "#c9ced6", Theme: "#e2b04a" };

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
      <line x1={sx(0)} y1={pad} x2={sx(0)} y2={h - pad} stroke="#23272f" />
      <line x1={pad} y1={sy(0)} x2={w - pad} y2={sy(0)} stroke="#23272f" />
      {corner.map(([t, x, y, a]) => (
        <text key={t} x={x} y={y} textAnchor={a} fill="#98a2b3" fontSize="12">
          {t}
        </text>
      ))}
      <text x={w / 2} y={h - 8} textAnchor="middle" fill="#98a2b3" fontSize="11">
        1 month vs SPY (%)
      </text>
      <text x={12} y={h / 2} textAnchor="middle" fill="#98a2b3" fontSize="11" transform={`rotate(-90 12 ${h / 2})`}>
        1 week vs SPY (%)
      </text>
      {points.map((p) => (
        <g key={p.ticker}>
          <circle cx={sx(p.x)} cy={sy(p.y)} r={4} fill={GROUP_COLOURS[p.group] ?? "#8b949e"} />
          <text x={sx(p.x)} y={sy(p.y) - 7} textAnchor="middle" fill="#e8eaed" fontSize="10">
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
      ...LAYOUT,
    });
    for (const [k, colour] of [["ratio_5d", "#8fb5ff"], ["ratio_10d", T.ma]] as const) {
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
