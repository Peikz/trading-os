// Positions (trading_os/positions_view.py): a card per open position with the price (the last
// close; live from Alpaca only when its keys are set on the server), open R and P&L, the
// distance to the stop, and what the plan says today, with earnings within two sessions.
import { useEffect, useState } from "react";
import { api, type Positions as Data } from "../api";
import { chartLink } from "../components/Card";
import { Metric } from "../components/Table";
import { signed, usd } from "../format";

export function Positions() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.positions().then(setData, (e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <div>
      <h2>Positions</h2>
      {data.cards.length === 0 ? (
        <p className="muted">
          No open positions. Your fills come in through the Journal (import or log).
        </p>
      ) : (
        <>
          <div className="metrics">
            <Metric label="Open positions" value={String(data.totals.positions)} />
            <Metric label="Open P&L (at the close)" value={usd(data.totals.open_pnl)} />
            <Metric label="At risk to stops" value={usd(data.totals.at_risk_usd)} />
          </div>
          <p className="muted">Prices: {data.source}</p>
          <div className="cards">
            {data.cards.map((c) => (
              <article className="card" key={c.ticker} aria-label={`${c.ticker} position`}>
                <header>
                  <b className="ticker">{c.ticker}</b> · {c.setup}{" "}
                  <span className="muted">
                    {c.direction} · {c.shares.toLocaleString("en-US")} sh · in {c.entry_date}
                  </span>{" "}
                  <a href={chartLink(c.ticker)}>📈 Chart</a>
                </header>
                <div className="metrics">
                  <Metric
                    label="Price"
                    value={c.price === null ? "n/a" : c.price.toFixed(2)}
                    delta={signed(c.move_pct, 1, "%")}
                  />
                  <Metric
                    label="Open R"
                    value={c.open_r === null ? "n/a" : signed(c.open_r, 2, "R")}
                    delta={usd(c.pnl)}
                  />
                  <Metric
                    label="To stop"
                    value={c.to_stop_pct === null ? "no stop" : `${c.to_stop_pct.toFixed(1)}%`}
                    delta={c.stop === null ? undefined : `stop ${c.stop.toFixed(2)}`}
                  />
                </div>
                {c.facts.length > 0 && (
                  <ul>
                    {c.facts.map((f) => (
                      <li key={f}>{f.startsWith("⚠️") ? <b>{f}</b> : f}</li>
                    ))}
                  </ul>
                )}
              </article>
            ))}
          </div>
          <p className="muted">{data.caption}</p>
        </>
      )}
    </div>
  );
}
