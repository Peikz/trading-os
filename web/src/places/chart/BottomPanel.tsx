// The Chart's bottom panel: what the API already knows about the active stock. Plan (the newest
// scan hit's decision and numbers), Notes (the stock's notes), Position (an open position's
// card), Journal (closed trades, and the grading form for a scan hit) and Lines (typed-in
// trend lines, anchored VWAPs, minute bars). It collapses to its tab strip.
import { useEffect, useState } from "react";
import { api, type BoardRow, type ChartData, type ChartListRow, type PositionCard, type Row } from "../../api";
import { GradeBadge } from "../../components/Card";
import { cell, signed, usd } from "../../format";
import { IntradaySection, Notes, TypeIn } from "../../pages/Chart";
import { HitGrading } from "../../pages/Screener";
import { Icon } from "../../ui/Icon";
import { Numbers } from "../today/PlanCard";

const TABS = [
  ["plan", "Plan"],
  ["notes", "Notes"],
  ["position", "Position"],
  ["journal", "Journal"],
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
          {!symbol && <p className="muted">Pick a stock to see its plan, notes, position and journal.</p>}
          {symbol && tab === "plan" && <PlanTab symbol={symbol} />}
          {symbol && tab === "notes" && <Notes ticker={symbol} onMessage={onMessage} />}
          {symbol && tab === "position" && <PositionTab symbol={symbol} />}
          {symbol && tab === "journal" && <JournalTab symbol={symbol} row={row} />}
          {symbol && tab === "lines" && data && data.ticker === symbol && (
            <>
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

const TRADE_COLUMNS = ["entry_date", "exit_date", "setup", "entry_avg", "exit_avg", "pnl", "r_multiple"];

function JournalTab({ symbol, row }: { symbol: string; row: ChartListRow | undefined }) {
  const [trades, setTrades] = useState<Row[] | null>(null);
  useEffect(() => {
    let live = true;
    setTrades(null);
    api.journalClosed().then(
      (j) => live && setTrades(j.trades.filter((t) => t.ticker === symbol)),
      () => live && setTrades([]),
    );
    return () => {
      live = false;
    };
  }, [symbol]);
  return (
    <div>
      {trades === null ? (
        <p className="muted">Loading…</p>
      ) : trades.length === 0 ? (
        <p className="muted">No closed trades in {symbol} yet.</p>
      ) : (
        <div className="table-wrap">
          <table aria-label={`Closed trades in ${symbol}`}>
            <thead>
              <tr>
                {TRADE_COLUMNS.map((c) => (
                  <th key={c}>{c.replace(/_/g, " ")}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={String(t.trade_id ?? i)}>
                  {TRADE_COLUMNS.map((c) => (
                    <td key={c} className="num">
                      {c === "r_multiple" && typeof t[c] === "number" ? signed(t[c] as number, 2, "R") : cell(c, t[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {row?.signal_id && <HitGrading ticker={symbol} signalId={row.signal_id} scanLabel={row.setup} />}
    </div>
  );
}
