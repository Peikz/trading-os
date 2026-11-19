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
import { Treemap, type TreeItem } from "./market/Treemap";

const PERIODS: [string, string, number][] = [["Today", "1D", 3], ["1 week", "1W", 6], ["1 month", "1M", 12], ["3 months", "3M", 20]];

export function Market({ tab = "overview" }: { tab?: string }) {
  const [p, setP] = useState<Record<string, string>>({ period: "Today" });
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
          <div className="tiles-row" aria-label="Market tiles">
            {data.tiles!.map((t) => (
              <Tile key={t.label} tile={t} />
            ))}
          </div>
          {data.sectors ? <Heatmap data={data} onPeriod={(v) => set("period", v)} /> : <p className="muted">No sector data yet: it comes from TradingView, and with each EOD run.</p>}
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

const DOTS: Record<string, string> = { "🟢": "green", "🟡": "amber", "🔴": "red" };

/** A market tile: a word as a dot and the word, a number as a number with its move. */
function Tile({ tile }: { tile: { label: string; value: string; delta: string | null } }) {
  const first = [...tile.value][0] ?? "";
  const level = DOTS[first];
  const text = stripIcons(tile.value);
  const isNumber = /^[\d,.]+$/.test(text);
  const word = level ? text[0] + text.slice(1).toLowerCase() : text;
  return (
    <div className="mtile">
      <span className="muted">{plain(tile.label).text}</span>
      {isNumber ? (
        <b className="num">{text}</b>
      ) : (
        <b className="word">
          <span className={`dot ${level ?? ""}`} aria-hidden="true" /> {word}
        </b>
      )}
      {tile.delta && (
        <span className="num" style={{ color: deltaColour(tile.label, tile.delta) }}>
          {tile.delta}
        </span>
      )}
    </div>
  );
}

/** The sector treemap with its period chips, and the sector table under it. */
function Heatmap({ data, onPeriod }: { data: MarketPage; onPeriod: (period: string) => void }) {
  const table = data.sectors!;
  const col = table.columns.find((c) => c.endsWith(" %")) ?? "";
  const items: TreeItem[] = table.rows
    .filter((r) => (data.picked ?? []).includes(String(r.group)))
    .map((r) => ({
      key: String(r.ticker),
      name: String(r.name),
      ticker: String(r.ticker),
      group: String(r.group),
      value: typeof r[col] === "number" ? (r[col] as number) : null,
    }));
  const meta = PERIODS.find(([k]) => k === data.period) ?? PERIODS[0];
  return (
    <section aria-label="Sector heatmap">
      <div className="row heat-head">
        <h3 style={{ margin: 0 }}>Sectors</h3>
        <div className="seg-line" role="group" aria-label="Change over">
          {PERIODS.map(([k, label]) => (
            <button key={k} aria-pressed={data.period === k} onClick={() => onPeriod(k)}>
              {label}
            </button>
          ))}
        </div>
        <span className="muted legend">Equal tiles · colour is the change · click a sector to screen its stocks</span>
      </div>
      <Treemap items={items} period={meta[1]} scale={meta[2]} />
      <ApiTableView label="Indexes, sectors and themes" table={table} />
      <p className="muted">{data.sector_caption}</p>
    </section>
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
          Strong: QQQ light green and a healthy IBD uptrend. Weak: QQQ light red and an IBD
          correction. Mixed: everything else. A summary of facts, not a rule.
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
const GROUP_COLOURS: Record<string, string> = { Index: "var(--accent)", Sector: "var(--text-2)", Theme: "var(--warn)" };

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
      <line x1={sx(0)} y1={pad} x2={sx(0)} y2={h - pad} stroke="var(--border)" />
      <line x1={pad} y1={sy(0)} x2={w - pad} y2={sy(0)} stroke="var(--border)" />
      {corner.map(([t, x, y, a]) => (
        <text key={t} x={x} y={y} textAnchor={a} fill="var(--text-2)" fontSize="12">
          {t}
        </text>
      ))}
      <text x={w / 2} y={h - 8} textAnchor="middle" fill="var(--text-2)" fontSize="11">
        1 month vs SPY (%)
      </text>
      <text x={12} y={h / 2} textAnchor="middle" fill="var(--text-2)" fontSize="11" transform={`rotate(-90 12 ${h / 2})`}>
        1 week vs SPY (%)
      </text>
      {points.map((p) => (
        <g key={p.ticker}>
          <circle cx={sx(p.x)} cy={sy(p.y)} r={4} fill={GROUP_COLOURS[p.group] ?? "var(--text-3)"} />
          <text x={sx(p.x)} y={sy(p.y) - 7} textAnchor="middle" fill="var(--text-1)" fontSize="10">
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
    for (const [k, colour] of [["ratio_5d", T.accent], ["ratio_10d", T.ma]] as const) {
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
