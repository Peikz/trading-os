// The notebook's left side: search (filters as you type), Today, then Daily notes by month,
// Trades (open and closed, filterable), Stocks, Pages and Tags with their counts, and "New page".
// Every row is a link to its page (`#/journal/notes?p=...`), so the browser's back button works.
// "Note on a stock" opens any stock's page from its ticker or name, so a stock can get its first
// note right here (before 26 Nov 2026 it needed a note written somewhere else first).
import { type ReactNode, useMemo, useState } from "react";
import type { NbDaily, NbIndex, NbTrade } from "../api";
import { GradeBadge } from "../components/Card";
import { signed } from "../format";
import { Icon } from "../ui/Icon";
import { dayTitle, type Entry, monthOf, monthTitle, search, snippet, tagCounts } from "./model";
import { noteHref } from "./env";
import { matchSymbols, useSymbols } from "../shell/symbols";

const TICKER = /^\$?[A-Za-z][A-Za-z0-9.-]{0,9}$/;

/** Type a ticker or a company, Enter or a click opens that stock's page to write a note. */
function StockStart() {
  const symbols = useSymbols();
  const [q, setQ] = useState("");
  const hits = useMemo(() => (symbols && q.trim() ? matchSymbols(symbols, q, 6) : []), [symbols, q]);
  const open = (ticker: string) => {
    window.location.hash = noteHref(`stock:${ticker.toUpperCase()}`);
    setQ("");
  };
  return (
    <div className="nb-stock-start">
      <input
        type="text"
        aria-label="Note on a stock"
        placeholder="Note on a stock: ticker or name"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== "Enter") return;
          e.preventDefault();
          const text = q.trim();
          if (hits.length) open(hits[0].ticker);
          else if (TICKER.test(text)) open(text.replace(/^\$/, ""));
        }}
      />
      {hits.length > 0 && (
        <div className="nb-stock-hits" aria-label="Stocks to write a note on">
          {hits.map((h) => (
            <Row key={h.ticker} href={noteHref(`stock:${h.ticker}`)} title={h.name}>
              <b className="nb-tk">${h.ticker}</b>
              <span className="nb-sub nb-snip">{h.name}</span>
            </Row>
          ))}
        </div>
      )}
    </div>
  );
}

function remembered(key: string, fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(`nb.${key}`);
    return v === null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}

function Section({
  id, title, count, children, start = true, extra,
}: { id: string; title: string; count?: number; children: ReactNode; start?: boolean; extra?: ReactNode }) {
  const [open, setOpen] = useState(() => remembered(id, start));
  const toggle = () => {
    setOpen(!open);
    try {
      window.localStorage.setItem(`nb.${id}`, open ? "0" : "1");
    } catch {
      /* private window: the section just does not remember */
    }
  };
  return (
    <section className="nb-sec" aria-label={title}>
      <div className="nb-sec-head">
        <button type="button" className="ghost nb-sec-btn" aria-expanded={open} onClick={toggle}>
          <Icon name={open ? "down" : "right"} size={14} />
          <span>{title}</span>
          {count !== undefined && <span className="nb-count">{count}</span>}
        </button>
        {extra}
      </div>
      {open && <div className="nb-sec-body">{children}</div>}
    </section>
  );
}

function Row({ href, active, children, title }: { href: string; active?: boolean; children: ReactNode; title?: string }) {
  return (
    <a className={`nb-row${active ? " on" : ""}`} href={href} aria-current={active ? "page" : undefined} title={title}>
      {children}
    </a>
  );
}

interface Filters {
  tag: string;
  setup: string;
  grade: string;
  conviction: string;
  result: string;
}
const NO_FILTER: Filters = { tag: "", setup: "", grade: "", conviction: "", result: "" };

export function filterTrades(trades: NbTrade[], f: Filters): NbTrade[] {
  return trades.filter(
    (t) =>
      (!f.tag || t.tags.includes(f.tag)) &&
      (!f.setup || t.setup === f.setup) &&
      (!f.grade || t.grade === f.grade) &&
      (!f.conviction || String(t.conviction ?? "") === f.conviction) &&
      (!f.result || (f.result === "win" ? (t.r ?? t.pnl ?? 0) > 0 : f.result === "loss" ? (t.r ?? t.pnl ?? 0) <= 0 && t.status === "closed" : t.status === "open")),
  );
}

function TradeRow({ t, active }: { t: NbTrade; active: boolean }) {
  return (
    <Row href={noteHref(`trade:${t.id}`)} active={active}>
      <b className="nb-tk">{t.ticker}</b>
      <span className="nb-sub">{(t.exit_date ?? t.entry_date ?? "").slice(5)}</span>
      <span className="grow" />
      {t.r !== null && <span className={`num ${t.r >= 0 ? "up" : "down"}`}>{signed(t.r, 1, "R")}</span>}
      {t.grade && <GradeBadge grade={t.grade} />}
    </Row>
  );
}

export function Sidebar({
  index, entries, selected, query, onQuery, onNewPage, todayHasNote,
}: {
  index: NbIndex;
  entries: Entry[];
  /** `today`, `daily:<id>`, `trade:<id>`, `stock:<T>`, `page:<slug>`, `tag:<t>` */
  selected: string | null;
  query: string;
  onQuery: (q: string) => void;
  onNewPage: () => void;
  todayHasNote: boolean;
}) {
  const [filters, setFilters] = useState<Filters>(NO_FILTER);
  const [filtering, setFiltering] = useState(false);
  const tags = useMemo(() => tagCounts(entries), [entries]);
  const found = useMemo(() => (query.trim() ? search(entries, query) : []), [entries, query]);
  // A ticker typed in the search also offers that stock's page (to write its first note)
  const symbols = useSymbols();
  const stockHits = useMemo(
    () => (symbols && TICKER.test(query.trim()) ? matchSymbols(symbols, query, 20).filter((h) => h.ticker === query.trim().replace(/^\$/, "").toUpperCase()) : []),
    [symbols, query],
  );
  const months = useMemo(() => {
    const by = new Map<string, NbDaily[]>();
    for (const d of index.daily) by.set(monthOf(d.date), [...(by.get(monthOf(d.date)) ?? []), d]);
    return [...by].sort((a, b) => b[0].localeCompare(a[0]));
  }, [index.daily]);
  const open = filterTrades(index.trades.filter((t) => t.status === "open"), filters);
  const closed = filterTrades(index.trades.filter((t) => t.status === "closed"), filters)
    .sort((a, b) => (b.exit_date ?? "").localeCompare(a.exit_date ?? ""));
  const setups = [...new Set(index.trades.map((t) => t.setup).filter(Boolean))].sort();
  const filterOn = Object.values(filters).some(Boolean);
  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setFilters({ ...filters, [k]: e.target.value });
  const thisMonth = monthOf(index.today);

  return (
    <nav className="nb-side" aria-label="Notebook">
      <div className="nb-search">
        <Icon name="search" size={15} />
        <input
          type="search"
          aria-label="Search notes"
          placeholder="Search notes…"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
        />
      </div>
      <div className="nb-side-actions">
        <a className={`nb-row nb-today${selected === "today" ? " on" : ""}`} href={noteHref("today")}>
          <Icon name="today" size={16} />
          <b>Today</b>
          <span className="nb-sub">{todayHasNote ? dayTitle(index.today).split(",")[0] : "start a note"}</span>
        </a>
        <button type="button" className="nb-new" onClick={onNewPage}>
          <Icon name="plus" size={15} />
          New page
        </button>
      </div>

      {query.trim() ? (
        <div className="nb-results" aria-label="Search results">
          {stockHits.map((h) => (
            <Row key={`stock-${h.ticker}`} href={noteHref(`stock:${h.ticker}`)} active={selected === `stock:${h.ticker}`}>
              <span className="nb-col">
                <span className="nb-title">Note on ${h.ticker}</span>
                <span className="nb-sub nb-snip">{h.name}</span>
              </span>
            </Row>
          ))}
          {found.length === 0 && stockHits.length === 0 && <p className="muted nb-empty">No note matches “{query.trim()}”.</p>}
          {found.slice(0, 60).map((e, i) => (
            <Row key={`${e.ref}-${i}`} href={noteHref(e.ref)} active={selected === e.ref}>
              <span className="nb-col">
                <span className="nb-title">{e.title}</span>
                <span className="nb-sub nb-snip">{snippet(e.text, 70) || e.kind}</span>
              </span>
            </Row>
          ))}
        </div>
      ) : (
        <div className="nb-scroll">
          <Section id="daily" title="Daily notes" count={index.daily.length}>
            {months.length === 0 && <p className="muted nb-empty">No daily notes yet.</p>}
            {months.map(([month, days]) => (
              <Section key={month} id={`month-${month}`} title={monthTitle(month)} count={days.length} start={month === thisMonth}>
                {days.map((d) => (
                  <Row key={d.id} href={noteHref(`daily:${d.id}`)} active={selected === `daily:${d.id}`}>
                    <span className="nb-col">
                      <span className="nb-title">{dayTitle(d.date).replace(/ \d{4}$/, "")}</span>
                      <span className="nb-sub nb-snip">{snippet(d.text, 60)}</span>
                    </span>
                  </Row>
                ))}
              </Section>
            ))}
          </Section>

          <Section
            id="trades"
            title="Trades"
            count={index.trades.length}
            extra={
              <button
                type="button"
                className={`ghost icon-btn nb-filter-btn${filterOn ? " on" : ""}`}
                aria-label="Filter trades"
                aria-pressed={filtering}
                onClick={() => setFiltering(!filtering)}
              >
                <Icon name="sliders" size={15} />
              </button>
            }
          >
            {filtering && (
              <div className="nb-filters" role="group" aria-label="Trade filters">
                <select aria-label="Tag" value={filters.tag} onChange={set("tag")}>
                  <option value="">Any tag</option>
                  {tags.map((t) => <option key={t.tag} value={t.tag}>#{t.tag}</option>)}
                </select>
                <select aria-label="Setup" value={filters.setup} onChange={set("setup")}>
                  <option value="">Any setup</option>
                  {setups.map((s) => <option key={s}>{s}</option>)}
                </select>
                <select aria-label="Grade" value={filters.grade} onChange={set("grade")}>
                  <option value="">Any grade</option>
                  {["A+++", "A++", "A+", "A", "B", "C"].map((g) => <option key={g}>{g}</option>)}
                </select>
                <select aria-label="Conviction" value={filters.conviction} onChange={set("conviction")}>
                  <option value="">Any conviction</option>
                  <option value="1">1 small</option>
                  <option value="2">2 normal</option>
                  <option value="3">3 high</option>
                </select>
                <select aria-label="Result" value={filters.result} onChange={set("result")}>
                  <option value="">Win or loss</option>
                  <option value="win">Winners</option>
                  <option value="loss">Losers</option>
                  <option value="open">Open</option>
                </select>
                {filterOn && (
                  <button type="button" className="link" onClick={() => setFilters(NO_FILTER)}>Clear filters</button>
                )}
              </div>
            )}
            {index.trades.length === 0 && <p className="muted nb-empty">No trades yet. Import fills or log one.</p>}
            {index.trades.length > 0 && open.length + closed.length === 0 && <p className="muted nb-empty">No trade matches.</p>}
            {open.length > 0 && (
              <Section id="trades-open" title="Open" count={open.length}>
                {open.map((t) => <TradeRow key={t.id} t={t} active={selected === `trade:${t.id}`} />)}
              </Section>
            )}
            {closed.length > 0 && (
              <Section id="trades-closed" title="Closed" count={closed.length}>
                {closed.map((t) => <TradeRow key={t.id} t={t} active={selected === `trade:${t.id}`} />)}
              </Section>
            )}
          </Section>

          <Section id="stocks" title="Stocks" count={index.stocks.length}>
            <StockStart />
            {index.stocks.length === 0 && <p className="muted nb-empty">No stock notes yet. Type a ticker above to write the first.</p>}
            {index.stocks.map((s) => (
              <Row key={s.ticker} href={noteHref(`stock:${s.ticker}`)} active={selected === `stock:${s.ticker}`}>
                <b className="nb-tk">${s.ticker}</b>
                <span className="grow" />
                <span className="nb-count">{s.notes.length}</span>
              </Row>
            ))}
          </Section>

          <Section id="pages" title="Pages" count={index.pages.length}>
            {index.pages.length === 0 && <p className="muted nb-empty">No pages yet. “New page” starts one.</p>}
            {index.pages.map((p) => (
              <Row key={p.slug} href={noteHref(`page:${p.slug}`)} active={selected === `page:${p.slug}`}>
                <span className="nb-col">
                  <span className="nb-title">{p.title}</span>
                  <span className="nb-sub nb-snip">{snippet(p.text, 60)}</span>
                </span>
              </Row>
            ))}
          </Section>

          <Section id="tags" title="Tags" count={tags.length}>
            {tags.length === 0 && <p className="muted nb-empty">Write #tag anywhere in a note.</p>}
            {tags.map((t) => (
              <Row key={t.tag} href={noteHref(`tag:${t.tag}`)} active={selected === `tag:${t.tag}`}>
                <span>#{t.tag}</span>
                <span className="grow" />
                <span className="nb-count">{t.count}</span>
              </Row>
            ))}
          </Section>
        </div>
      )}
    </nav>
  );
}
