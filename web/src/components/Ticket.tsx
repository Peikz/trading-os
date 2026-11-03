// The Saxo ticket (trading_os.ticket via /api/ticket): the plan's order type by default, any
// other on a switch, an own price; shares keep the grade's risk. Every value has a copy
// button; "Placed in Saxo" saves it as a plan so the fill matches it. Nothing is sent to Saxo.
import { useEffect, useState } from "react";
import { api, type BoardRow, type TicketView } from "../api";
import { copy } from "../format";

export function Ticket({ row }: { row: BoardRow }) {
  const [kind, setKind] = useState<string | null>(null);
  const [price, setPrice] = useState<string>("");
  const [view, setView] = useState<TicketView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  // A new stock starts at its plan's order type and price
  useEffect(() => {
    setKind(null);
    setPrice("");
    setSaved(null);
  }, [row.ticker, row.scan]);

  const own = price === "" ? null : Number(price);
  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      api.ticket(row, kind, own).then(
        (v) => {
          if (!live) return;
          setView(v);
          setError(null);
          if (price === "" && v.plan_price) setPrice(v.plan_price.toFixed(2));
        },
        (e: Error) => live && setError(e.message),
      );
    }, 150);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `price` is read via `own`
  }, [row, kind, own]);

  if (error) return <p className="error">Ticket: {error}</p>;
  if (!view) return <p className="muted">Loading the ticket…</p>;

  const pick = (k: string) => {
    setKind(k);
    setPrice(""); // the new type's plan price
    setSaved(null);
  };
  const place = () =>
    api.placeTicket(row, view.kind, own).then(
      (r) => setSaved(r.message),
      (e: Error) => setSaved(`❌ ${e.message}`),
    );
  const t = view.ticket;

  return (
    <section className="ticket" aria-label="Saxo ticket">
      <div className="row">
        <label>
          Order type{" "}
          <select aria-label="Order type" value={view.kind} onChange={(e) => pick(e.target.value)}>
            {Object.entries(view.kinds).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
                {k === view.default ? " (plan)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label title="The plan's price; type your own to recompute the shares.">
          {view.price_label}{" "}
          <input
            aria-label={view.price_label}
            type="number"
            step="0.01"
            min="0"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
        </label>
      </div>
      {view.note && <p className="muted">{view.note}</p>}
      {view.error && <p className="warn">{view.error}</p>}
      {t && (
        <>
          {t.when && (
            <p>
              <b>When:</b> {t.when}
            </p>
          )}
          <dl className="lines">
            {t.lines.map((l) => (
              <div key={l.label}>
                <dt className="muted">{l.label}</dt>
                <dd>
                  <code>{l.value}</code>{" "}
                  <button
                    className="link"
                    aria-label={`Copy ${l.label}`}
                    onClick={() => copy(l.value).then(() => setCopied(l.label))}
                  >
                    {copied === l.label ? "✓" : "⧉"}
                  </button>
                </dd>
              </div>
            ))}
          </dl>
          <p className="muted">{t.caption}</p>
          <button onClick={place}>✅ Placed in Saxo: save as plan</button>
          {saved && <p className={saved.startsWith("❌") ? "error" : "ok"}>{saved}</p>}
        </>
      )}
    </section>
  );
}
