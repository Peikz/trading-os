// What the search finds beyond the stock rows (round 4, Streamlit's search page): for a ticker its
// scan-hit history (the last 30 runs), the lists, position and alerts it is on, and its notes; for
// words, your stock notes, daily notes, journal notes and the guide's lines. Read-only.
import { useEffect, useState } from "react";
import { api, type SearchTicker, type SearchWords } from "../api";
import { Table } from "../components/Table";
import { noteHref } from "../notebook/env";
import { hrefFor } from "../routes";

const TICKER = /^\$?[A-Za-z][A-Za-z0-9.-]{0,5}$/;
export const looksLikeTicker = (text: string) => TICKER.test(text.trim());
export const tickerOf = (text: string) => text.trim().replace(/^\$/, "").toUpperCase();

const cut = (t: string, n = 200) => (t.length > n ? `${t.slice(0, n)}…` : t);

export function SearchDetail({ text, onClose }: { text: string; onClose: () => void }) {
  const q = text.trim();
  const [ticker, setTicker] = useState<SearchTicker | null>(null);
  const [words, setWords] = useState<SearchWords | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setTicker(null);
    setWords(null);
    setFailed(false);
    if (!q) return;
    let live = true;
    const timer = setTimeout(() => {
      if (looksLikeTicker(q)) api.searchTicker(tickerOf(q)).then((r) => live && setTicker(r), () => live && setFailed(true));
      api.searchWords(q).then((r) => live && setWords(r), () => live && setFailed(true));
    }, 250);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [q]);

  if (!q) return null;
  const found = words ? words.stock.length + words.daily.length + words.journal.length + words.guide.length : 0;
  const loading = !failed && (words === null || (looksLikeTicker(q) && ticker === null));
  return (
    <div className="search-detail" aria-label="Search details" aria-live="polite">
      {failed && <p className="muted">The detail search is not available.</p>}
      {ticker && (
        <section aria-label={`${ticker.ticker} everywhere`}>
          <h4>
            {ticker.ticker} <span className="muted">scan hits (last {ticker.runs_searched} runs)</span>
          </h4>
          {ticker.hits.length === 0 ? (
            <p className="muted">None.</p>
          ) : (
            <Table
              label={`${ticker.ticker} scan hits`}
              columns={["run", "scan", "tier", "grade", "why", "points"]}
              rows={ticker.hits.map((h) => ({ ...h }))}
            />
          )}
          <p>
            <b>On:</b> {ticker.places.length ? ticker.places.join(", ") : "no list, position or alert"}
          </p>
          {ticker.notes.length > 0 && (
            <>
              <b>Notes</b>
              <ul className="sd-list">
                {ticker.notes.map((n, i) => (
                  <li key={i}>
                    <a href={noteHref(n.kind === "stock note" ? `stock:${ticker.ticker}` : `day:${n.date}`)} onClick={onClose}>
                      {n.date}
                    </a>{" "}
                    · {n.kind}: {cut(n.text)}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
      {words && found > 0 && (
        <section aria-label="Words in your notes and the guide">
          <h4>In your notes and the guide</h4>
          <ul className="sd-list">
            {words.stock.map((n, i) => (
              <li key={`s${i}`}>
                <a href={noteHref(`stock:${n.ticker}`)} onClick={onClose}>
                  {n.ticker}
                </a>{" "}
                · {n.date} · stock note: {cut(n.text)}
              </li>
            ))}
            {words.daily.map((n, i) => (
              <li key={`d${i}`}>
                <a href={noteHref(`day:${n.date}`)} onClick={onClose}>
                  {n.date}
                </a>{" "}
                · daily note: {cut(n.text)}
              </li>
            ))}
            {words.journal.map((n, i) => (
              <li key={`j${i}`}>
                {n.kind === "trade" ? (
                  <a href={noteHref(`trade:${n.ref_id}`)} onClick={onClose}>
                    journal (trade)
                  </a>
                ) : (
                  <span>
                    journal ({n.kind} {n.ref_id})
                  </span>
                )}
                : {cut(n.text)}
              </li>
            ))}
            {words.guide.map((g, i) => (
              <li key={`g${i}`}>
                <a href={hrefFor("lab", "guide")} onClick={onClose}>
                  <em>{g.section || "Guide"}</em>
                </a>
                : {g.line}
              </li>
            ))}
          </ul>
        </section>
      )}
      {words && found === 0 && !looksLikeTicker(q) && <p className="muted">Nothing found in your notes or the guide.</p>}
      {loading && <p className="muted">Searching your notes…</p>}
    </div>
  );
}
