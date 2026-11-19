// Today's Grid and List views (round 4, Streamlit's board modes). Grid: four charts at a time, two
// by two, one set of bars and indicator controls above them, flipped a page at a time. List: one
// card per stock with its facts, plan and why, twelve at a time. The Focus view is Today itself.
import { useState } from "react";
import type { Timeframe } from "../../api";
import { FactStrip, GradeBadge, KindBadge } from "../../components/Card";
import { stockLink } from "../../routes";
import { Icon } from "../../ui/Icon";
import { Segmented } from "../../ui/kit";
import { FocusChart, IndicatorMenu, TIMEFRAMES } from "./FocusChart";
import { anchorOf, changeOf, type Item, levelsOf, priceOf, statsOf } from "./model";
import { SidePanel } from "./Panels";

const label = (i: Item) => (i.row ? (i.kind === "watch" ? "Watching" : i.row.scan_label) : i.pos!.setup);

function Badge({ item }: { item: Item }) {
  if (item.kind === "watch" || item.kind === "position") return <KindBadge kind={item.kind} />;
  return <GradeBadge grade={item.row!.grade} />;
}

export const GRID = 4;

export function GridView({
  items,
  at,
  onAt,
  current,
  onSelect,
  tf,
  onTf,
  picked,
  onPicked,
}: {
  items: Item[];
  /** The page's first stock (a multiple of four) */
  at: number;
  onAt: (i: number) => void;
  current: string | null;
  onSelect: (key: string) => void;
  tf: Timeframe;
  onTf: (t: Timeframe) => void;
  picked: string[];
  onPicked: (p: string[]) => void;
}) {
  const pages = Math.max(1, Math.ceil(items.length / GRID));
  const page = Math.min(Math.floor(at / GRID), pages - 1);
  const first = page * GRID;
  const shown = items.slice(first, first + GRID);
  if (!items.length) return <p className="muted">Nothing in this list.</p>;
  return (
    <section className="grid-view" aria-label="Grid of charts">
      <div className="grid-bar">
        <button className="icon-btn" aria-label="Previous four" disabled={pages < 2} onClick={() => onAt(((page - 1 + pages) % pages) * GRID)}>
          <Icon name="left" />
        </button>
        <span className="muted" aria-live="polite">
          {first + 1}-{Math.min(first + GRID, items.length)} of {items.length}
        </span>
        <button className="icon-btn" aria-label="Next four" disabled={pages < 2} onClick={() => onAt(((page + 1) % pages) * GRID)}>
          <Icon name="right" />
        </button>
        <span className="grow" />
        <Segmented label="Bars" options={TIMEFRAMES.map((t) => [t, t] as const)} value={tf} onPick={onTf} />
        <IndicatorMenu picked={picked} onChange={onPicked} />
      </div>
      <div className="grid-cells">
        {shown.map((i) => (
          <article key={i.key} className={`grid-cell${current === i.key ? " active" : ""}`} aria-label={`${i.ticker} chart cell`} onClick={() => onSelect(i.key)}>
            <div className="grid-cell-head">
              <Badge item={i} />
              <b>{i.ticker}</b>
              <span className="muted">{label(i)}</span>
            </div>
            <FocusChart
              ticker={i.ticker}
              levels={levelsOf(i)}
              anchor={anchorOf(i)}
              tf={tf}
              onTf={onTf}
              picked={picked}
              onPicked={onPicked}
              price={priceOf(i)}
              change={changeOf(i)}
              height={300}
              tools={false}
            />
            <FactStrip stats={statsOf(i)} />
          </article>
        ))}
      </div>
    </section>
  );
}

const MORE = 12;

export function ListView({ items, slotNames }: { items: Item[]; slotNames: Record<string, string> }) {
  const [shown, setShown] = useState(MORE);
  if (!items.length) return <p className="muted">Nothing in this list.</p>;
  return (
    <section className="list-view" aria-label="List of cards">
      <p className="muted">
        {items.length} {items.length === 1 ? "signal" : "signals"}
      </p>
      <div className="list-cards">
        {items.slice(0, shown).map((i) => {
          const chg = changeOf(i);
          const from = (i.row?.runs ?? []).map((s) => slotNames[s] ?? s).join(" · ");
          return (
            <article key={i.key} className="list-card" aria-label={`${i.ticker} card`}>
              <header>
                <Badge item={i} />
                <b className="tk">{i.ticker}</b>
                <span className="muted">{label(i)}</span>
                {from && <small className="from-runs">{from}</small>}
                {typeof chg === "number" && (
                  <span className={`chg num ${chg >= 0 ? "up" : "down"}`}>
                    {chg >= 0 ? "+" : ""}
                    {chg.toFixed(1)}%
                  </span>
                )}
                <a href={stockLink(i.ticker)} className="muted">
                  Chart
                </a>
              </header>
              <FactStrip stats={statsOf(i)} label={`${i.ticker} key facts`} />
              <SidePanel item={i} />
            </article>
          );
        })}
      </div>
      {shown < items.length && (
        <button className="block" onClick={() => setShown((n) => n + MORE)}>
          Show {Math.min(MORE, items.length - shown)} more
        </button>
      )}
    </section>
  );
}
