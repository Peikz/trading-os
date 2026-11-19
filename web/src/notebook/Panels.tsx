// The notebook's right side and the tag view. A trade or a stock page gets its chart (entry, exit
// and stop for a trade); every page gets "Linked mentions" (the notes that link to it) and its
// tags. A tag opens as a list of everything that carries it, newest first, with a snippet.
import type { NbIndex, NbTrade } from "../api";
import { StockChart, TradeChart } from "../components/TradeChart";
import { signed } from "../format";
import { noteHref } from "./env";
import { type Entry, mentionsOf, newestFirst, snippet, tagCounts } from "./model";

const KIND_NAME = { daily: "Day", trade: "Trade", stock: "Stock", page: "Page" } as const;

function EntryRow({ e, query }: { e: Entry; query?: string }) {
  return (
    <a className="nb-hit" href={noteHref(e.ref)}>
      <span className="nb-hit-top">
        <b>{e.title}</b>
        <span className="nb-kind">{KIND_NAME[e.kind]}</span>
        <span className="grow" />
        <span className="nb-sub">{e.date}</span>
      </span>
      <span className="nb-snip nb-hit-snip">{snippet(e.text, 160) || (query ? "" : "No text yet")}</span>
    </a>
  );
}

export function TagView({ tag, entries }: { tag: string; entries: Entry[] }) {
  const mine = entries.filter((e) => e.tags.includes(tag)).sort(newestFirst);
  const related = tagCounts(mine).filter((t) => t.tag !== tag).sort((a, b) => b.count - a.count).slice(0, 8);
  return (
    <article className="nb-page" aria-label={`Tag ${tag}`}>
      <header className="nb-head">
        <div className="nb-title-row">
          <h2 className="nb-h">#{tag}</h2>
          <span className="grow" />
          <span className="muted">{mine.length} {mine.length === 1 ? "note" : "notes"}</span>
        </div>
        {related.length > 0 && (
          <div className="nb-props">
            <div className="nb-prop">
              <span className="nb-k">Also tagged</span>
              <span className="nb-chips">
                {related.map((t) => (
                  <a key={t.tag} className="nb-chip" href={noteHref(`tag:${t.tag}`)}>#{t.tag} {t.count}</a>
                ))}
              </span>
            </div>
          </div>
        )}
      </header>
      <div className="nb-hits">
        {mine.length === 0 && <p className="muted">Nothing carries #{tag}.</p>}
        {mine.map((e, i) => <EntryRow key={`${e.ref}-${i}`} e={e} />)}
      </div>
    </article>
  );
}

function Facts({ t }: { t: NbTrade }) {
  const price = (v: number | null) => (v === null ? "–" : v.toFixed(2));
  return (
    <dl className="nb-facts" aria-label="Trade facts">
      <div><dt>Entry</dt><dd>{price(t.entry)}</dd></div>
      <div><dt>Exit</dt><dd>{price(t.exit)}</dd></div>
      <div><dt>Stop</dt><dd>{price(t.stop)}</dd></div>
      {t.r !== null && <div><dt>R</dt><dd className={t.r >= 0 ? "up" : "down"}>{signed(t.r, 2, "R")}</dd></div>}
    </dl>
  );
}

export type Target =
  | { kind: "trade"; trade: NbTrade }
  | { kind: "stock"; ticker: string }
  | { kind: "page"; slug: string; ref: string }
  | { kind: "day"; date: string; ref: string | null }
  | { kind: "tag" };

export function RightPanel({ target, index, entries }: { target: Target; index: NbIndex; entries: Entry[] }) {
  void index;
  let mentions: Entry[] = [];
  let ref: string | null = null;
  if (target.kind === "trade") mentions = mentionsOf(entries, { kind: "stock", key: target.trade.ticker, self: `trade:${target.trade.id}` });
  else if (target.kind === "stock") mentions = mentionsOf(entries, { kind: "stock", key: target.ticker });
  else if (target.kind === "page") {
    ref = target.ref;
    const title = index.pages.find((p) => p.slug === target.slug)?.title ?? "";
    mentions = title ? mentionsOf(entries, { kind: "page", key: title, self: target.ref }) : [];
  } else if (target.kind === "day") {
    ref = target.ref;
    mentions = mentionsOf(entries, { kind: "day", key: target.date, self: target.ref ?? undefined });
  }
  const here = ref ? entries.find((e) => e.ref === ref) : undefined;
  const tags = here ? here.tags : [];
  const counts = new Map(tagCounts(entries).map((t) => [t.tag, t.count]));
  return (
    <div className="nb-right-in">
      {target.kind === "trade" && (
        <section aria-label="Trade chart">
          <TradeChart
            ticker={target.trade.ticker}
            entry={target.trade.entry_date ?? ""}
            exit={target.trade.exit_date ?? ""}
            stop={target.trade.stop}
            height={260}
          />
          <Facts t={target.trade} />
        </section>
      )}
      {target.kind === "stock" && (
        <section aria-label="Stock chart">
          <StockChart ticker={target.ticker} height={260} />
        </section>
      )}
      <section aria-label="Linked mentions">
        <h3 className="nb-side-h">Linked mentions <span className="nb-count">{mentions.length}</span></h3>
        {mentions.length === 0 && (
          <p className="muted nb-empty">
            {target.kind === "page" ? "Nothing links here yet. Write [[" + (index.pages.find((p) => p.slug === (target as { slug: string }).slug)?.title ?? "this page") + "]] in a note." : "No other note mentions this."}
          </p>
        )}
        {mentions.slice(0, 20).map((e, i) => <EntryRow key={`${e.ref}-${i}`} e={e} />)}
      </section>
      {tags.length > 0 && (
        <section aria-label="Tags of this page">
          <h3 className="nb-side-h">Tags</h3>
          <div className="nb-chips">
            {tags.map((t) => <a key={t} className="nb-chip" href={noteHref(`tag:${t}`)}>#{t} <span className="nb-count">{counts.get(t) ?? 1}</span></a>)}
          </div>
        </section>
      )}
    </div>
  );
}
