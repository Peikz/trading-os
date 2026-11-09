// The plan card leads with the decision (design review 4 Nov 2026): the grade, "Buy at 10:30
// New York" with the Copenhagen time under it, Entry / Stop / Shares / Risk, one primary
// button that copies the order for Saxo (the plan's order type), the order on one line with
// "Edit order" (order type and price; the shares follow so the risk stays the same), and
// "I placed it in Saxo", which saves the ticket as today's plan. Nothing is sent to Saxo.
import { useEffect, useState } from "react";
import { api, type BoardRow, type TicketView } from "../../api";
import { GradeBadge } from "../../components/Card";
import { copy, usd } from "../../format";
import { stripIcons } from "../../plain";
import { Icon } from "../../ui/Icon";

const GRADED = ["A++", "A+", "A", "B"];

/** The ticket for a row (`/api/ticket`): the plan's order type, or `kind` at `price`. */
export function useTicket(row: BoardRow | null, kind: string | null, price: number | null) {
  const [view, setView] = useState<TicketView | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!row) return;
    let live = true;
    const timer = setTimeout(() => {
      api.ticket(row, kind, price).then(
        (v) => {
          if (!live) return;
          setView(v);
          setError(null);
        },
        (e: Error) => live && setError(e.message),
      );
    }, 120);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [row, kind, price]);
  return { view: row ? view : null, error };
}

/** Entry, stop, shares and risk: the ticket's when there is one, else the run's plan. */
export function planNumbers(row: BoardRow, view: TicketView | null) {
  const t = view?.ticket;
  const n = (k: string) => (typeof row[k] === "number" ? (row[k] as number) : null);
  return {
    entry: t ? t.est_entry : n("plan_entry"),
    stop: t ? t.stop : (n("plan_stop") ?? n("grade_stop")),
    shares: t ? t.shares : n("plan_shares"),
    risk: t ? t.risk_usd : n("plan_risk_usd"),
  };
}

const price = (x: number | null) => (x === null ? "–" : x.toFixed(2));

export function Numbers({ row, view, three }: { row: BoardRow; view: TicketView | null; three?: boolean }) {
  const p = planNumbers(row, view);
  return (
    <div className={`quad${three ? " trio" : ""}`} aria-label="The plan's numbers">
      <div>
        <span>Entry</span>
        <b className="num">{price(p.entry)}</b>
      </div>
      <div>
        <span>Stop</span>
        <b className="num">{price(p.stop)}</b>
      </div>
      <div>
        <span>Shares</span>
        <b className="num">{p.shares === null ? "–" : p.shares.toLocaleString("en-US")}</b>
      </div>
      {!three && (
        <div>
          <span>Risk</span>
          <b className="num">{p.risk === null ? "–" : usd(p.risk)}</b>
        </div>
      )}
    </div>
  );
}

/** The order as typed into Saxo, with the ticker in front (the copy button's text). */
export const orderText = (row: BoardRow, view: TicketView | null) =>
  view?.ticket?.summary ? `${row.ticker}: ${view.ticket.summary}` : null;

export function CopyOrder({ row, view, big }: { row: BoardRow; view: TicketView | null; big?: boolean }) {
  const [copied, setCopied] = useState<"yes" | "blocked" | null>(null);
  useEffect(() => setCopied(null), [row.ticker, view]);
  const text = orderText(row, view);
  return (
    <button
      className={`primary block${big ? " big" : ""}`}
      disabled={!text}
      onClick={() =>
        text &&
        copy(text).then(
          () => setCopied("yes"),
          () => setCopied("blocked"),
        )
      }
    >
      <Icon name={copied === "yes" ? "check" : "copy"} />
      {copied === "yes"
        ? "Copied: paste or type it into Saxo"
        : copied === "blocked"
          ? "The browser blocked copying: use the order line"
          : "Copy order for Saxo"}
    </button>
  );
}

export function PlanCard({ row }: { row: BoardRow }) {
  const [kind, setKind] = useState<string | null>(null);
  const [own, setOwn] = useState("");
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [copiedLine, setCopiedLine] = useState<string | null>(null);

  // A new stock starts at its plan's order type and price
  useEffect(() => {
    setKind(null);
    setOwn("");
    setEditing(false);
    setSaved(null);
  }, [row.ticker, row.scan]);

  const priceNow = own === "" ? null : Number(own);
  const { view, error } = useTicket(row, kind, priceNow);
  const d = row.decision;
  const t = view?.ticket;

  const place = () =>
    api.placeTicket(row, view?.kind ?? kind, priceNow).then(
      (r) => setSaved(r.message),
      (e: Error) => setSaved(`Error: ${e.message}`),
    );

  return (
    <section className="card plan" aria-label={`${row.ticker} plan`}>
      <div className="head">
        <GradeBadge grade={row.grade} large />
        <span className="tk">{row.ticker}</span>
        <span className="muted">{row.scan_label}</span>
      </div>
      {d ? (
        <>
          <div className="decision">{d.text}</div>
          <div className="decision-sub">{[d.local, d.day].filter(Boolean).join(" · ") || " "}</div>
        </>
      ) : (
        <>
          <div className="decision">{GRADED.includes(row.grade) ? "Buy by the study's plan" : "Not a buy by the study"}</div>
          <div className="decision-sub">
            {GRADED.includes(row.grade) ? row.run_label : "Graded C: no tested edge. Sized as a B for reference."}
          </div>
        </>
      )}
      <Numbers row={row} view={view} />
      <CopyOrder row={row} view={view} />
      <div className="order-line">
        <code>{t?.summary ?? (view?.note || error || "Working out the order…")}</code>
        <button className="link" aria-expanded={editing} onClick={() => setEditing((e) => !e)}>
          {editing ? "Done" : "Edit order"}
        </button>
      </div>
      {editing && !view && <p className="muted hint">Loading the order…</p>}
      {editing && view && (
        <div className="edit-order" aria-label="Edit order">
          <div className="row">
            <label>
              Order type{" "}
              <select
                aria-label="Order type"
                value={view.kind}
                onChange={(e) => {
                  setKind(e.target.value);
                  setOwn("");
                  setSaved(null);
                }}
              >
                {Object.entries(view.kinds).map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                    {k === view.default ? " (plan)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label title="The plan's price; type your own and the shares follow so the risk stays the same">
              {view.price_label}{" "}
              <input
                aria-label={view.price_label}
                type="number"
                step="0.01"
                min="0"
                placeholder={view.plan_price?.toFixed(2) ?? ""}
                value={own}
                onChange={(e) => setOwn(e.target.value)}
              />
            </label>
          </div>
          {t && (
            <>
              {t.when && <p className="muted hint">When: {t.when}</p>}
              <dl className="lines">
                {t.lines.map((l) => (
                  <div key={l.label}>
                    <dt>{l.label}</dt>
                    <dd>
                      <code>{l.value}</code>
                      <button
                        className="ghost icon-btn"
                        aria-label={`Copy ${l.label}`}
                        onClick={() => copy(l.value).then(() => setCopiedLine(l.label), () => setCopiedLine(null))}
                      >
                        <Icon name={copiedLine === l.label ? "check" : "copy"} size={16} />
                      </button>
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="muted hint">{t.caption}. The shares follow the price so the risk stays the same.</p>
            </>
          )}
        </div>
      )}
      {view?.error && <p className="warn hint">{view.error}</p>}
      {view?.note && t && <p className="muted hint">{view.note}</p>}
      {error && <p className="error hint">Ticket: {error}</p>}
      <button className="block" onClick={place} disabled={!t} title="Saves this order as today's plan, so your fill matches it in the Journal">
        I placed it in Saxo
      </button>
      {saved && (
        <p className={saved.startsWith("Error") ? "error hint" : "ok hint"} role="status">
          {saved}
        </p>
      )}
    </section>
  );
}

export function WhyCard({ row }: { row: BoardRow }) {
  const w = row.why;
  const empty = !w || (!w.summary && !w.points.length && !w.lines.length);
  const facts = row.facts.map(stripIcons).filter(Boolean);
  return (
    <section className="card why" aria-label={`Why ${row.grade}`}>
      <h3>Why {row.grade}</h3>
      {w?.summary && <p>{w.summary}</p>}
      {!empty && (
        <ul>
          {w!.points.map((p) => (
            <li key={p.text} className={p.ok ? "" : "muted"}>
              <span className={p.ok ? "yes" : "no"}>
                <Icon name={p.ok ? "check" : "x"} size={16} label={p.ok ? "held" : "not held"} />
              </span>
              <span>{p.text}</span>
            </li>
          ))}
          {w!.lines.map((l) => (
            <li key={l}>
              <span className="no">
                <Icon name="right" size={16} />
              </span>
              <span>{l}</span>
            </li>
          ))}
        </ul>
      )}
      {empty && facts.length > 0 && (
        <ul>
          {facts.map((f) => (
            <li key={f}>
              <span className="no">
                <Icon name="right" size={16} />
              </span>
              <span>{f}</span>
            </li>
          ))}
        </ul>
      )}
      {empty && facts.length === 0 && <p className="muted">No reasons saved with this signal.</p>}
      <p className="muted hint">
        Found by {row.scan_label}, {row.run_label}. Facts about past rules, not advice.
      </p>
    </section>
  );
}
