// The Chart's bottom panel: what the API already knows about the active stock. Plan (the newest
// scan hit's decision and numbers), Notes (the stock's notebook page: its notes, its trades and the
// grading form of a scan hit), Position (an open position's card) and Lines (a horizontal line at a
// price, the saved lines with remove, typed-in trend lines, anchored VWAPs, minute bars). It
// collapses to its tab strip.
import { useEffect, useState } from "react";
import { api, type BoardRow, type ChartData, type ChartListRow, type PositionCard, type SavedMark } from "../../api";
import { GradeBadge } from "../../components/Card";
import { usd } from "../../format";
import { IntradaySection, TypeIn } from "../../pages/Chart";
import { Icon } from "../../ui/Icon";
import { Numbers } from "../today/PlanCard";
import { NotesTab } from "./NotesTab";

const TABS = [
  ["plan", "Plan"],
  ["notes", "Notes"],
  ["position", "Position"],
  ["lines", "Lines"],
] as const;
type Tab = (typeof TABS)[number][0];

export function BottomPanel({
  symbol,
  data,
  row,
  open,
  onToggle,
  onMessage,
  onSaved,
}: {
  symbol: string;
  data: ChartData | null;
  row: ChartListRow | undefined;
  open: boolean;
  onToggle: () => void;
  onMessage: (t: string) => void;
  onSaved: () => void;
}) {
  const [tab, setTab] = useState<Tab>("plan");
  return (
    <section className={`ws-bottom${open ? "" : " shut"}`} aria-label="Stock panel">
      <div className="ws-tabs" role="tablist" aria-label="Stock panel tabs">
        {TABS.map(([id, text]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id && open}
            className={tab === id && open ? "on" : ""}
            onClick={() => {
              setTab(id);
              if (!open) onToggle();
            }}
          >
            {text}
          </button>
        ))}
        <span className="grow" />
        <button className="ghost icon-btn" aria-label={open ? "Hide the stock panel" : "Show the stock panel"} aria-expanded={open} onClick={onToggle}>
          <Icon name={open ? "down" : "up"} size={16} />
        </button>
      </div>
      {open && (
        <div className="ws-tab-body" role="tabpanel">
          {!symbol && <p className="muted">Pick a stock to see its plan, notes and position.</p>}
          {symbol && tab === "plan" && <PlanTab symbol={symbol} />}
          {symbol && tab === "notes" && <NotesTab symbol={symbol} row={row} />}
          {symbol && tab === "position" && <PositionTab symbol={symbol} />}
          {symbol && tab === "lines" && data && data.ticker === symbol && (
            <>
              <SavedLines ticker={symbol} data={data} version={data.marks.length} onSaved={onSaved} onMessage={onMessage} />
              <TypeIn ticker={symbol} data={data} onSaved={onSaved} onMessage={onMessage} />
              <IntradaySection ticker={symbol} />
              <p className="muted hint">{data.note}</p>
              <a href={data.tradingview} target="_blank" rel="noreferrer">
                Open in TradingView
              </a>
            </>
          )}
        </div>
      )}
    </section>
  );
}

function PlanTab({ symbol }: { symbol: string }) {
  const [rows, setRows] = useState<BoardRow[] | null>(null);
  useEffect(() => {
    let live = true;
    setRows(null);
    api.today("graded", [symbol]).then(
      (r) => live && setRows(r.rows),
      () => live && setRows([]),
    );
    return () => {
      live = false;
    };
  }, [symbol]);
  if (rows === null) return <p className="muted">Loading…</p>;
  if (rows.length === 0) return <p className="muted">No scan hit for {symbol} in the newest runs, so no plan.</p>;
  const r = rows[0];
  return (
    <div className="plan-tab">
      <div className="plan-head">
        <GradeBadge grade={r.grade} />
        <b>{r.scan_label}</b>
        <span className="muted">{r.run_label}</span>
      </div>
      {r.decision && <p className="decision-line">{r.decision.text}</p>}
      <Numbers row={r} view={null} three />
      {r.why?.summary && <p className="muted">{r.why.summary}</p>}
      {r.facts.length > 0 && <p className="muted">{r.facts.join(" · ")}</p>}
      {rows.length > 1 && (
        <p className="muted">Also hit: {rows.slice(1).map((x) => `${x.scan_label} (${x.grade})`).join(", ")}</p>
      )}
    </div>
  );
}

function PositionTab({ symbol }: { symbol: string }) {
  const [card, setCard] = useState<PositionCard | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    setCard(undefined);
    api.positions().then(
      (p) => live && setCard(p.cards.find((c) => c.ticker === symbol) ?? null),
      () => live && setCard(null),
    );
    return () => {
      live = false;
    };
  }, [symbol]);
  if (card === undefined) return <p className="muted">Loading…</p>;
  if (card === null) return <p className="muted">No open position in {symbol}.</p>;
  const stats: [string, string][] = [
    ["Shares", `${card.shares}`],
    ["Entry", card.entry.toFixed(2)],
    ["Price", card.price === null ? "–" : card.price.toFixed(2)],
    ["P&L", card.pnl === null ? "–" : usd(card.pnl)],
    ["Stop", card.stop === null ? "–" : card.stop.toFixed(2)],
  ];
  return (
    <div className="plan-tab">
      <div className="plan-head">
        <b>{card.setup || "Open position"}</b>
        <span className="muted">{card.direction}</span>
      </div>
      <div className="quad trio" aria-label="The position's numbers">
        {stats.map(([k, v]) => (
          <div key={k}>
            <span>{k}</span>
            <b className="num">{v}</b>
          </div>
        ))}
      </div>
      {card.facts.length > 0 && <p className="muted">{card.facts.join(" · ")}</p>}
    </div>
  );
}

/** Lines on the stock: "＋ Horizontal line" at a price, and every saved line, level and anchor with a
 * remove button (Streamlit's "Lines and levels"). The price starts at the last close. */
function SavedLines({
  ticker,
  data,
  version,
  onSaved,
  onMessage,
}: {
  ticker: string;
  data: ChartData;
  version: number;
  onSaved: () => void;
  onMessage: (t: string) => void;
}) {
  const last = data.candles.length ? data.candles[data.candles.length - 1].close : 0;
  const [price, setPrice] = useState(last ? last.toFixed(2) : "");
  const [marks, setMarks] = useState<SavedMark[] | null>(null);
  const [again, setAgain] = useState(0);
  useEffect(() => setPrice(last ? last.toFixed(2) : ""), [ticker, last]);
  useEffect(() => {
    let live = true;
    api.savedMarks(ticker).then((m) => live && setMarks(m), () => live && setMarks([]));
    return () => {
      live = false;
    };
  }, [ticker, version, again]);
  const fail = (e: Error) => onMessage(`Error: ${e.message}`);
  const add = () =>
    api.addLevel(ticker, Number(price)).then(() => {
      onMessage(`Line saved at ${Number(price).toFixed(2)}.`);
      setAgain((n) => n + 1);
      onSaved();
    }, fail);
  return (
    <section className="lines-tab" aria-label={`Lines on ${ticker}`}>
      <b>Lines on {ticker}</b> <span className="muted">· saved for this stock, on every device</span>
      <div className="row">
        <label>
          Price{" "}
          <input aria-label="Level price" type="number" step="0.01" min="0" value={price} onChange={(e) => setPrice(e.target.value)} />
        </label>
        <button disabled={!(Number(price) > 0)} onClick={add}>
          <Icon name="plus" size={16} />
          Horizontal line
        </button>
      </div>
      {marks && marks.length === 0 && <p className="muted">No lines yet. Add a level above, or draw with the line tool.</p>}
      {marks && marks.length > 0 && (
        <ul className="saved-lines" aria-label="Saved lines">
          {marks.map((m) => (
            <li key={m.mark_id}>
              <span>{m.text}</span>
              <button
                className="ghost icon-btn"
                aria-label={`Remove: ${m.text}`}
                onClick={() =>
                  api.removeMark(ticker, m.mark_id).then(() => {
                    setAgain((n) => n + 1);
                    onSaved();
                  }, fail)
                }
              >
                <Icon name="x" size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
