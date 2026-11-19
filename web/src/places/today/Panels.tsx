// The right-hand panel of a Today item: a scan hit's plan and why, a position's numbers, or a watched
// stock's one line. Shared by the Focus view and the List view's cards.
import type { PositionCard } from "../../api";
import { KindBadge } from "../../components/Card";
import { signed, usd } from "../../format";
import { stripIcons } from "../../plain";
import { hrefFor, stockLink } from "../../routes";
import { GRADES, type Item, sectorOf } from "./model";
import { PlanCard, WhyCard } from "./PlanCard";

export function SidePanel({ item }: { item: Item }) {
  if (item.pos) return <PositionPanel p={item.pos} />;
  const row = item.row!;
  if (item.kind === "watch") {
    return (
      <section className="card" aria-label={`${row.ticker} watch`}>
        <div className="plan head" style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <KindBadge kind="watch" />
          <b>{row.ticker}</b>
          <span className="muted">{sectorOf(row)}</span>
        </div>
        <p className="muted">On your watchlist. Not a scan hit today, so there is no plan or grade.</p>
        <a href={stockLink(row.ticker)}>Open the full chart</a>
      </section>
    );
  }
  if (!GRADES.includes(row.grade)) {
    return (
      <section className="card" aria-label={`${row.ticker} screen`}>
        <b>{row.ticker}</b> <span className="muted">{row.run_label}</span>
        <p className="muted">A screen is a list to look at, not a tested setup: no grade, no buy.</p>
      </section>
    );
  }
  return (
    <>
      <PlanCard row={row} />
      <WhyCard row={row} />
    </>
  );
}

export function PositionPanel({ p }: { p: PositionCard }) {
  return (
    <section className="card plan" aria-label={`${p.ticker} position`}>
      <div className="head">
        <KindBadge kind="position" />
        <span className="tk">{p.ticker}</span>
        <span className="muted">{p.setup}</span>
      </div>
      <div className="decision">
        {p.shares.toLocaleString("en-US")} shares since {p.entry_date}
      </div>
      <div className="decision-sub">
        {p.direction} at {p.entry.toFixed(2)}
      </div>
      <div className="quad">
        <div>
          <span>Price</span>
          <b className="num">{p.price === null ? "–" : p.price.toFixed(2)}</b>
        </div>
        <div>
          <span>Open R</span>
          <b className={`num ${p.open_r === null ? "" : p.open_r >= 0 ? "up" : "down"}`}>
            {p.open_r === null ? "–" : signed(p.open_r, 2, "R")}
          </b>
        </div>
        <div>
          <span>P&L</span>
          <b className={`num ${p.pnl === null ? "" : p.pnl >= 0 ? "up" : "down"}`}>{usd(p.pnl)}</b>
        </div>
        <div>
          <span>To stop</span>
          <b className="num">{p.to_stop_pct === null ? "no stop" : `${p.to_stop_pct.toFixed(1)}%`}</b>
        </div>
      </div>
      {p.facts.length > 0 && (
        <>
          <h3>What the plan says</h3>
          <ul>
            {p.facts.map((f) => (
              <li key={f} className={f.startsWith("⚠") ? "warn" : ""}>
                {stripIcons(f)}
              </li>
            ))}
          </ul>
        </>
      )}
      <a href={hrefFor("journal", "positions")}>All positions in the Journal</a>
    </section>
  );
}
