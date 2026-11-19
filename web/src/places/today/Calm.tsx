// Today, the calm layout (owner-approved mockup, 19 Nov 2026). The screen answers one question:
// "what do I do now?" A thin market line on top; left, the stocks to act on (grade, ticker, when
// to buy, change); in the middle ONE big card for the one selected, with the action, a big chart
// with the entry and stop lines, three big numbers and the copy button; right, your positions,
// alerts and today's note. The why, the key facts, the Saxo order (edit, per-value copy, "I placed
// it in Saxo") and the note and price alert sit behind "Why and facts": moved, not removed.
import { type RefObject, useEffect, useRef, useState } from "react";
import { api, type Alerts, type BoardRow, type Market, type NextScan, type PositionCard, type Timeframe } from "../../api";
import { FactStrip, GradeBadge, KindBadge } from "../../components/Card";
import { signed, usd } from "../../format";
import { stripIcons } from "../../plain";
import { hrefFor, stockLink } from "../../routes";
import { Icon } from "../../ui/Icon";
import { FocusChart } from "./FocusChart";
import {
  alertOf,
  anchorOf,
  changeOf,
  GRADES,
  holdDay,
  type Item,
  levelsOf,
  nextScanBits,
  priceOf,
  reasonShort,
  sectorOf,
  statsOf,
  whenOf,
} from "./model";
import { CopyOrder, EditOrder, OrderLine, PlaceOrder, planNumbers, usePlan, VALUES_EVENT, WhyCard } from "./PlanCard";
import { WatchButton, WatchNote } from "./WatchNote";

const PHONE_CHART = 220;

/** The chart takes what the window leaves under the card's other rows: the numbers and the buttons
 * stay on screen at 900 px high, and the chart is never smaller than 280 or taller than 520. */
function useChartHeight(phone: boolean): number {
  const [h, setH] = useState(() => window.innerHeight);
  useEffect(() => {
    const on = () => setH(window.innerHeight);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return phone ? PHONE_CHART : Math.max(280, Math.min(520, h - 540));
}

// --- the market line

export function MarketLine({ next }: { next: NextScan | null }) {
  const [market, setMarket] = useState<Market | null>(null);
  useEffect(() => {
    const load = () => api.market().then(setMarket, () => setMarket(null));
    load();
    window.addEventListener("trading-os:refresh", load);
    return () => window.removeEventListener("trading-os:refresh", load);
  }, []);
  const mood = market?.mood;
  const bits = next ? nextScanBits(next.when) : null;
  return (
    <div className="market-line" aria-label="Market">
      <span className="word">
        <span className={`dot ${mood?.level ?? ""}`} aria-hidden="true" />
        {mood?.word ?? (market ? "No market data" : "Market…")}
      </span>
      {(mood?.reasons ?? []).map((r) => (
        <span key={r.text} className="reason">
          {reasonShort(r.text)}
        </span>
      ))}
      <span className="grow" />
      {next && bits && (
        <span className="next">
          Next scan {bits.ny && bits.cph ? (
            <>
              <span className="ny">{bits.ny} NY · </span>
              {bits.cph} CPH
            </>
          ) : (
            bits.raw
          )}
        </span>
      )}
    </div>
  );
}

// --- the stocks to act on

export function GroupLine({
  watch,
  c,
  more,
  onMore,
}: {
  watch: number;
  c: number;
  more: "watch" | "c" | null;
  onMore: (m: "watch" | "c" | null) => void;
}) {
  if (!watch && !c) return null;
  return (
    <p className="group-line">
      {watch > 0 && (
        <button className="link" aria-expanded={more === "watch"} onClick={() => onMore(more === "watch" ? null : "watch")}>
          Watching {watch}
        </button>
      )}
      {c > 0 && (
        <button className="link" aria-expanded={more === "c"} onClick={() => onMore(more === "c" ? null : "c")}>
          C setups {c}
        </button>
      )}
    </p>
  );
}

export function ActRow({
  item,
  active,
  onPick,
  slotNames,
}: {
  item: Item;
  active: boolean;
  onPick: () => void;
  slotNames: Record<string, string>;
}) {
  const chg = changeOf(item);
  const many = Object.keys(slotNames).length > 1;
  const from = (item.row?.runs ?? []).map((s) => slotNames[s] ?? s).join(" · ");
  return (
    <button aria-current={active} className={active ? "active" : ""} onClick={onPick}>
      {item.kind === "watch" ? <KindBadge kind="watch" /> : <GradeBadge grade={item.row!.grade} />}
      <span className="tk">{item.ticker}</span>
      <span className="setup">
        {whenOf(item)}
        {from && many && <small className="from-runs">{from}</small>}
      </span>
      {typeof chg === "number" && (
        <span className={`chg num ${chg >= 0 ? "up" : "down"}`}>
          {chg >= 0 ? "+" : ""}
          {chg.toFixed(1)}%
        </span>
      )}
    </button>
  );
}

/** The phone's stocks of today as chips, 44 px tall; the one on screen is outlined. */
export function Chips({ items, current, onPick }: { items: Item[]; current: string | null; onPick: (key: string) => void }) {
  const on = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    on.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [current]);
  return (
    <div className="today-chips" role="group" aria-label="Today's stocks">
      {items.map((i) => (
        <button
          key={i.key}
          ref={current === i.key ? on : undefined}
          className="today-chip"
          aria-current={current === i.key}
          onClick={() => onPick(i.key)}
        >
          {i.kind === "watch" ? <KindBadge kind="watch" /> : <GradeBadge grade={i.row!.grade} />}
          {i.ticker}
        </button>
      ))}
    </div>
  );
}

// --- the right side: positions, alerts, the day's note

export function PositionsList({
  cards,
  current,
  onPick,
}: {
  cards: PositionCard[];
  current: string | null;
  onPick: (key: string) => void;
}) {
  const open = cards.reduce((s, p) => s + (p.open_r ?? 0), 0);
  return (
    <section className="rail-section" aria-label="Positions">
      <div className="rail-head">
        <h2>Positions</h2>
        {cards.length > 0 && (
          <span className={`num ${open >= 0 ? "up" : "down"}`}>{signed(open, 1, "R")} open</span>
        )}
      </div>
      {cards.length === 0 && <p className="muted">No open positions.</p>}
      <ul className="pos-list">
        {cards.map((p) => {
          const h = holdDay(p);
          const key = `position:${p.ticker}`;
          return (
            <li key={p.ticker}>
              <button aria-current={current === key} className={current === key ? "active" : ""} onClick={() => onPick(key)}>
                <span className="pos-top">
                  <b>{p.ticker}</b>
                  <span className={`num ${p.open_r === null ? "" : p.open_r >= 0 ? "up" : "down"}`}>
                    {p.open_r === null ? "–" : signed(p.open_r, 1, "R")}
                  </span>
                </span>
                <span className="pos-sub">
                  <span>
                    Day {h.day} of {h.of}
                  </span>
                  <span>{p.to_stop_pct === null ? "No stop" : `Stop ${p.to_stop_pct.toFixed(1)} % away`}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function AlertsLine() {
  const [alerts, setAlerts] = useState<Alerts | null>(null);
  useEffect(() => {
    api.alerts().then(setAlerts, () => setAlerts(null));
  }, []);
  const fired = alerts?.fired.length ?? 0;
  const waiting = alerts?.alerts.length ?? 0;
  return (
    <section className="rail-section" aria-label="Alerts">
      <div className="rail-head">
        <h2>Alerts</h2>
      </div>
      <p className="muted">
        {alerts === null ? "…" : `${fired === 0 ? "None fired." : `${fired} fired.`} ${waiting} waiting.`}
      </p>
    </section>
  );
}

// --- the big card

/** The disclosure: a button that shows or hides what the card keeps out of the way. */
function Disclosure({ open, onToggle, id }: { open: boolean; onToggle: () => void; id: string }) {
  return (
    <button className="ghost disclose" aria-expanded={open} aria-controls={id} onClick={onToggle}>
      {open ? "Hide why and facts" : "Why and facts"}
      <Icon name={open ? "up" : "down"} size={16} />
    </button>
  );
}

/** N writes a note: open the disclosure the note lives in, then focus it. */
function useNoteFocus(signal: number, open: boolean, setOpen: (o: boolean) => void, noteRef: RefObject<HTMLTextAreaElement>) {
  const handled = useRef(signal);
  useEffect(() => {
    if (signal === handled.current) return;
    if (!open) {
      setOpen(true);
      return;
    }
    handled.current = signal;
    noteRef.current?.focus();
  }, [signal, open, setOpen, noteRef]);
}

interface CardProps {
  item: Item;
  phone: boolean;
  tf: Timeframe;
  onTf: (t: Timeframe) => void;
  picked: string[];
  onPicked: (p: string[]) => void;
  watching: boolean;
  onWatch: () => void;
  onMessage: (t: string) => void;
  noteRef: RefObject<HTMLTextAreaElement>;
  noteSignal: number;
}

function CardTop({ item, watching, onWatch }: Pick<CardProps, "item" | "watching" | "onWatch">) {
  const row = item.row;
  const price = priceOf(item);
  const chg = changeOf(item);
  const setup = item.pos ? item.pos.setup : item.kind === "watch" ? sectorOf(row!) : row!.scan_label;
  return (
    <div className="calm-top">
      {item.kind === "watch" || item.kind === "position" ? (
        <KindBadge kind={item.kind} />
      ) : (
        <GradeBadge grade={row!.grade} large />
      )}
      <h2 className="tk">{item.ticker}</h2>
      <span className="setup">{setup}</span>
      <WatchButton watching={watching} onToggle={onWatch} compact />
      <span className="grow" />
      {price !== null && <span className="last num">{price.toFixed(2)}</span>}
      {chg !== null && (
        <span className={`chg num ${chg >= 0 ? "up" : "down"}`}>
          {chg >= 0 ? "+" : ""}
          {chg.toFixed(1)}%
        </span>
      )}
    </div>
  );
}

function CardChart({ item, phone, tf, onTf, picked, onPicked }: Pick<CardProps, "item" | "phone" | "tf" | "onTf" | "picked" | "onPicked">) {
  const height = useChartHeight(phone);
  return (
    <FocusChart
      ticker={item.ticker}
      levels={levelsOf(item)}
      anchor={anchorOf(item)}
      tf={tf}
      onTf={onTf}
      picked={picked}
      onPicked={onPicked}
      height={height}
      head={false}
      link={false}
    />
  );
}

function BigNumbers({ cells }: { cells: [string, string, string?][] }) {
  return (
    <div className="big-nums" aria-label="The plan's numbers">
      {cells.map(([label, value, tone]) => (
        <div key={label}>
          <span>{label}</span>
          <b className={`num ${tone ?? ""}`}>{value}</b>
        </div>
      ))}
    </div>
  );
}

const price2 = (x: number | null) => (x === null ? "–" : x.toFixed(2));

/** A graded hit: the decision, the chart, Buy at / Stop / Shares, and the copy button. */
function GradedCard(props: CardProps) {
  const { item, phone, noteRef, noteSignal, onMessage, watching, onWatch } = props;
  const row = item.row as BoardRow;
  const plan = usePlan(row);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const on = () => setOpen(true); // T: the Saxo values are inside
    window.addEventListener(VALUES_EVENT, on);
    return () => window.removeEventListener(VALUES_EVENT, on);
  }, []);
  useNoteFocus(noteSignal, open, setOpen, noteRef);
  const p = planNumbers(row, plan.view);
  const d = row.decision;
  const isBuy = ["A+++", "A++", "A+", "A", "B"].includes(row.grade);
  const id = `why-${row.ticker}`;
  return (
    <section className="calm-card" aria-label={`${row.ticker} plan`}>
      <CardTop item={item} watching={watching} onWatch={onWatch} />
      <p className="calm-action">
        <span className="decision">{d?.text ?? (isBuy ? "Buy by the study's plan" : "Not a buy by the study")}</span>{" "}
        <span className="decision-sub">
          {d ? [d.local, d.day].filter(Boolean).join(" · ") : isBuy ? row.run_label : "Graded C: no tested edge. Sized as a B for reference."}
        </span>
      </p>
      <CardChart {...props} />
      <BigNumbers
        cells={[
          ["Buy at", price2(p.entry)],
          ["Stop", price2(p.stop)],
          ["Shares", p.shares === null ? "–" : p.shares.toLocaleString("en-US")],
        ]}
      />
      <div className="calm-actions">
        <div className="copy-dock">
          <CopyOrder row={row} view={plan.view} big={phone} />
        </div>
        <a className="btn-link" href={stockLink(row.ticker)}>
          Open on Chart
        </a>
        <Disclosure open={open} onToggle={() => setOpen(!open)} id={id} />
      </div>
      {open && (
        <div className="calm-more" id={id}>
          <WhyCard row={row} />
          <FactStrip stats={statsOf(item)} />
          <section className="card saxo" aria-label="Saxo order">
            <h3>The order in Saxo</h3>
            {p.risk !== null && <p className="muted">Risk {usd(p.risk)}</p>}
            <OrderLine plan={plan} />
            <EditOrder plan={plan} />
            <PlaceOrder plan={plan} />
          </section>
          <WatchNote
            ticker={row.ticker}
            alertDefault={alertOf(item)}
            watching={watching}
            onToggleWatch={onWatch}
            noteRef={noteRef}
            onMessage={onMessage}
            showWatch={false}
          />
        </div>
      )}
    </section>
  );
}

/** An open position: Open R / Stop / Shares; the plan's lines and the note behind the disclosure. */
function PositionBig(props: CardProps) {
  const { item, noteRef, noteSignal, onMessage, watching, onWatch } = props;
  const p = item.pos as PositionCard;
  const [open, setOpen] = useState(false);
  useNoteFocus(noteSignal, open, setOpen, noteRef);
  const h = holdDay(p);
  const id = `why-${p.ticker}`;
  return (
    <section className="calm-card" aria-label={`${p.ticker} position`}>
      <CardTop item={item} watching={watching} onWatch={onWatch} />
      <p className="calm-action">
        <span className="decision">
          {p.shares.toLocaleString("en-US")} shares since {p.entry_date}
        </span>{" "}
        <span className="decision-sub">
          {p.direction} at {p.entry.toFixed(2)} · day {h.day} of {h.of}
        </span>
      </p>
      <CardChart {...props} />
      <BigNumbers
        cells={[
          ["Open R", p.open_r === null ? "–" : signed(p.open_r, 2, "R"), p.open_r === null ? "" : p.open_r >= 0 ? "up" : "down"],
          ["Stop", price2(p.stop)],
          ["Shares", p.shares.toLocaleString("en-US")],
        ]}
      />
      <div className="calm-actions">
        <a className="btn-link" href={stockLink(p.ticker)}>
          Open on Chart
        </a>
        <Disclosure open={open} onToggle={() => setOpen(!open)} id={id} />
      </div>
      {open && (
        <div className="calm-more" id={id}>
          <section className="card" aria-label={`${p.ticker} position facts`}>
            <dl className="lines">
              <div>
                <dt>Price</dt>
                <dd>{price2(p.price)}</dd>
              </div>
              <div>
                <dt>P&amp;L</dt>
                <dd className={p.pnl === null ? "" : p.pnl >= 0 ? "up" : "down"}>{usd(p.pnl)}</dd>
              </div>
              <div>
                <dt>To stop</dt>
                <dd>{p.to_stop_pct === null ? "no stop" : `${p.to_stop_pct.toFixed(1)}%`}</dd>
              </div>
            </dl>
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
          <WatchNote
            ticker={p.ticker}
            alertDefault={alertOf(item)}
            watching={watching}
            onToggleWatch={onWatch}
            noteRef={noteRef}
            onMessage={onMessage}
            showWatch={false}
          />
        </div>
      )}
    </section>
  );
}

/** A watched stock or a screen's hit: no plan or grade, so the facts and the note. */
function PlainCard(props: CardProps) {
  const { item, noteRef, noteSignal, onMessage, watching, onWatch } = props;
  const row = item.row as BoardRow;
  const [open, setOpen] = useState(false);
  useNoteFocus(noteSignal, open, setOpen, noteRef);
  const watch = item.kind === "watch";
  const id = `why-${row.ticker}`;
  return (
    <section className="calm-card" aria-label={`${row.ticker} ${watch ? "watch" : "screen"}`}>
      <CardTop item={item} watching={watching} onWatch={onWatch} />
      <p className="calm-action">
        <span className="decision-sub">
          {watch
            ? "On your watchlist. Not a scan hit today, so there is no plan or grade."
            : "A screen is a list to look at, not a tested setup: no grade, no buy."}
        </span>
      </p>
      <CardChart {...props} />
      <FactStrip stats={statsOf(item)} />
      <div className="calm-actions">
        <a className="btn-link" href={stockLink(row.ticker)}>
          Open on Chart
        </a>
        <Disclosure open={open} onToggle={() => setOpen(!open)} id={id} />
      </div>
      {open && (
        <div className="calm-more" id={id}>
          <WatchNote
            ticker={row.ticker}
            alertDefault={alertOf(item)}
            watching={watching}
            onToggleWatch={onWatch}
            noteRef={noteRef}
            onMessage={onMessage}
            showWatch={false}
          />
        </div>
      )}
    </section>
  );
}

/** The one big card of the selected stock (keyed by the item, so each starts closed). */
export function StockCard(props: CardProps) {
  const { item } = props;
  if (item.pos) return <PositionBig key={item.key} {...props} />;
  const row = item.row!;
  if (item.kind === "watch" || !GRADES.includes(row.grade)) return <PlainCard key={item.key} {...props} />;
  return <GradedCard key={item.key} {...props} />;
}
