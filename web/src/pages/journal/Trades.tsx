// The Journal's trades: the closed-trade table on the left, the selected trade on the right (its
// chart with your fills marked, the facts, and the grade / conviction / notes form). On a phone
// the list is the screen and a tap opens the trade full screen with a back button. Facts from
// trading_os/journal_view.py; the grade and conviction are yours (append-only in the data repo).
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type JournalClosed, type Row } from "../../api";
import { GradeBadge } from "../../components/Card";
import { GradeForm } from "../../components/GradeForm";
import { RCurve } from "../../components/RCurve";
import { TradeChart } from "../../components/TradeChart";
import { Metric, Table } from "../../components/Table";
import { signed, usd } from "../../format";
import { stockLink } from "../../routes";
import { Icon } from "../../ui/Icon";
import { PHONE, useMedia } from "../../ui/kit";

const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const text = (v: unknown): string => (typeof v === "string" ? v : "");
const dayOf = (v: unknown): string => text(v).slice(0, 10);

export function Conviction({ value }: { value: unknown }) {
  const c = num(value);
  return c ? (
    <span className="conv" title={`Conviction ${c}: 1 small, 2 normal, 3 high`}>
      ◆{c}
    </span>
  ) : (
    <span className="muted">–</span>
  );
}

function RValue({ v }: { v: unknown }) {
  const r = num(v);
  if (r === null) return <span className="muted">–</span>;
  return <span className={r >= 0 ? "up" : "down"}>{signed(r, 2, "R")}</span>;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="fact">
      <small>{label}</small>
      <span>{children}</span>
    </div>
  );
}

function TradeDetail({
  trade,
  onBack,
  onSaved,
  phone,
}: {
  trade: Row;
  onBack: () => void;
  onSaved: () => void;
  phone: boolean;
}) {
  const ticker = text(trade.ticker);
  const price = (v: unknown) => (num(v) === null ? "–" : num(v)!.toFixed(2));
  return (
    <section className={`trade-detail card${phone ? " phone-full" : ""}`} aria-label={`${ticker} trade`}>
      <div className="trade-head">
        {phone && (
          <button className="ghost icon-btn back-btn" aria-label="Back to the trades" onClick={onBack}>
            <Icon name="back" />
          </button>
        )}
        <b className="ticker">{ticker}</b>
        <span className="muted">
          {text(trade.direction)} · {dayOf(trade.entry_date)} → {dayOf(trade.exit_date)}
        </span>
        <span className="grow" />
        {text(trade.grade) && <GradeBadge grade={text(trade.grade)} />}
        <Conviction value={trade.conviction} />
        <a href={stockLink(ticker)}>Full chart</a>
      </div>
      <TradeChart ticker={ticker} entry={dayOf(trade.entry_date)} exit={dayOf(trade.exit_date)} />
      <div className="facts-grid">
        <Fact label="R">
          <RValue v={trade.r_multiple} />
        </Fact>
        <Fact label="P&L">{usd(num(trade.pnl))}</Fact>
        <Fact label="Setup">{text(trade.setup) || "–"}</Fact>
        <Fact label="Entry">{price(trade.entry_avg)}</Fact>
        <Fact label="Exit">{price(trade.exit_avg)}</Fact>
        <Fact label="Shares">{num(trade.quantity)?.toLocaleString("en-US") ?? "–"}</Fact>
        <Fact label="Held">{num(trade.sessions_held) === null ? "–" : `${trade.sessions_held} sessions`}</Fact>
        <Fact label="MFE / MAE">
          {num(trade.mfe_r) === null ? "–" : `${signed(num(trade.mfe_r), 1, "R")} / ${signed(num(trade.mae_r), 1, "R")}`}
        </Fact>
        <Fact label="Exit efficiency">
          {num(trade.exit_efficiency) === null ? "–" : `${(num(trade.exit_efficiency)! * 100).toFixed(0)}%`}
        </Fact>
        <Fact label="Signal">{text(trade.signal_scan) || "–"}</Fact>
      </div>
      <GradeForm
        kind="trade"
        refId={String(trade.trade_id)}
        title={`${ticker} trade: grade, conviction, notes`}
        onSaved={onSaved}
      />
    </section>
  );
}

export function Trades() {
  const phone = useMedia(PHONE);
  const [data, setData] = useState<JournalClosed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [pick, setPick] = useState<string | null>(null);
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    api.journalClosed().then(setData, (e: Error) => setError(e.message));
  }, [version]);
  useEffect(() => {
    const on = () => setVersion((v) => v + 1);
    window.addEventListener("trading-os:journal", on);
    return () => window.removeEventListener("trading-os:journal", on);
  }, []);

  // Newest exit first
  const trades = useMemo(
    () => [...(data?.trades ?? [])].sort((a, b) => dayOf(b.exit_date).localeCompare(dayOf(a.exit_date))),
    [data],
  );
  const current = trades.find((t) => String(t.trade_id) === pick) ?? (phone ? undefined : trades[0]);
  const step = useCallback(
    (by: number) => {
      if (!trades.length) return;
      const at = current ? trades.indexOf(current) : -1;
      const next = trades[Math.max(0, Math.min(trades.length - 1, at + by))];
      setPick(String(next.trade_id));
    },
    [trades, current],
  );
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "j") step(1);
    else if (e.key === "ArrowUp" || e.key === "k") step(-1);
    else return;
    e.preventDefault();
  };
  useEffect(() => {
    // Keep the selected row in view as the arrows move it
    list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: "nearest" });
  }, [current]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!trades.length) return <p className="muted">No closed trades yet. Import fills or log a trade.</p>;
  const s = data.stats;
  return (
    <section>
      <div className="metrics">
        <Metric label="Closed trades" value={String(s.trades)} />
        <Metric label="Win rate" value={s.win_rate === null ? "n/a" : `${s.win_rate.toFixed(0)}%`} />
        <Metric label="Avg R" value={s.avg_r === null ? "n/a" : s.avg_r.toFixed(2)} />
        <Metric label="Total P&L" value={usd(s.pnl)} />
      </div>
      <div className="journal-split">
        <div className="trade-list" ref={list} onKeyDown={onKey}>
          <div className="table-wrap">
            <table aria-label="Closed trades">
              <thead>
                <tr>
                  <th>Exit</th>
                  <th>Stock</th>
                  <th className="setup">Setup</th>
                  <th>R</th>
                  <th>P&L</th>
                  <th>Grade</th>
                  <th title="Conviction: 1 small, 2 normal, 3 high">Conv.</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => {
                  const on = current === t;
                  const id = String(t.trade_id);
                  return (
                    <tr
                      key={id}
                      className={`clickable${on ? " active" : ""}`}
                      aria-selected={on}
                      tabIndex={0}
                      onClick={() => setPick(id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") setPick(id);
                      }}
                    >
                      <td>{dayOf(t.exit_date)}</td>
                      <td className="tk">{text(t.ticker)}</td>
                      <td className="setup">{text(t.setup) || "–"}</td>
                      <td>
                        <RValue v={t.r_multiple} />
                      </td>
                      <td>{usd(num(t.pnl))}</td>
                      <td>{text(t.grade) ? <GradeBadge grade={text(t.grade)} /> : <span className="muted">–</span>}</td>
                      <td>
                        <Conviction value={t.conviction} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted hint">{data.caption}</p>
          {data.by_conviction.length > 0 && (
            <details>
              <summary>By conviction (1 small · 2 normal · 3 high)</summary>
              <Table
                label="By conviction"
                columns={["conviction", "trades", "win_pct", "mean_r", "total_r"]}
                rows={data.by_conviction}
              />
            </details>
          )}
          {data.curve.length > 0 && <RCurve points={data.curve} />}
        </div>
        {current && (
          <TradeDetail
            key={String(current.trade_id)}
            trade={current}
            phone={phone}
            onBack={() => setPick(null)}
            onSaved={() => setVersion((v) => v + 1)}
          />
        )}
      </div>
    </section>
  );
}
