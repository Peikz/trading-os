// The market as one row of tiles above the board: QQQ light, heat, IBD state, SPY, QQQ, VIX.
import { useEffect, useState } from "react";
import { api, type Market } from "../api";
import { deltaColour } from "../format";

export function MarketTiles() {
  const [market, setMarket] = useState<Market | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.market().then(setMarket, (e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="muted">Market: {error}</p>;
  if (!market) return <div className="tiles muted">Loading the market…</div>;
  if (market.tiles.length === 0) return <p className="muted">No market row yet.</p>;
  return (
    <section aria-label="Market">
      <div className="tiles">
        {market.tiles.map((t) => (
          <div className="tile" key={t.label}>
            <span className="muted">{t.label}</span> <b>{t.value}</b>
            {t.delta && (
              <span
                className={deltaColour(t.label, t.delta) ? "" : "muted"}
                style={{ color: deltaColour(t.label, t.delta) }}
              >
                {" "}
                {t.delta}
              </span>
            )}
          </div>
        ))}
        {market.details.length > 0 && (
          <button className="link" onClick={() => setOpen(!open)}>
            {open ? "Hide details" : "Market details"}
          </button>
        )}
      </div>
      {open && (
        <ul className="details">
          {market.details.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
