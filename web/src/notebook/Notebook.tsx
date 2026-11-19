// The Journal as a notebook (Obsidian / Notion / OneNote feel, 18 Nov 2026): a sidebar of every
// note (search, Today, daily notes by month, trades, stocks, pages, tags), the page in a clean
// editor with its properties under the title, and a right panel (the chart of a trade or stock,
// linked mentions, tags). Everything is saved by itself. Daily, stock and trade notes keep their
// own files; only the free pages are new (data/journal/pages/). On a phone the sidebar is the first
// screen and a note opens full screen with a back arrow.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type NbIndex } from "../api";
import { Icon } from "../ui/Icon";
import { PHONE, useMedia } from "../ui/kit";
import { useSymbols } from "../shell/symbols";
import { type NbEnv, NbEnvContext, noteHref } from "./env";
import { entriesOf, parseSelection, tagCounts } from "./model";
import { DailyPage, FreePage, type Patch, StockPage, TradePage } from "./PageViews";
import { RightPanel, TagView, type Target } from "./Panels";
import { Sidebar } from "./Sidebar";

function useIndex() {
  const [index, setIndex] = useState<NbIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(
    () => api.notebook().then((i) => (setIndex(i), setError(null)), (e: Error) => setError(e.message)),
    [],
  );
  useEffect(() => {
    void reload();
    window.addEventListener("trading-os:journal", reload);
    return () => window.removeEventListener("trading-os:journal", reload);
  }, [reload]);
  const patch: Patch = useCallback((fn) => setIndex((i) => (i ? fn(i) : i)), []);
  return { index, error, reload, patch };
}

function usePersisted(key: string, fallback: boolean): [boolean, (v: boolean) => void] {
  let start = fallback;
  try {
    const v = window.localStorage.getItem(`nb.${key}`);
    if (v !== null) start = v === "1";
  } catch {
    /* no storage: not remembered */
  }
  const [on, set] = useState(start);
  return [
    on,
    (v) => {
      set(v);
      try {
        window.localStorage.setItem(`nb.${key}`, v ? "1" : "0");
      } catch {
        /* no storage */
      }
    },
  ];
}

export function Notebook({ params }: { params: URLSearchParams }) {
  const phone = useMedia(PHONE);
  const { index, error, patch } = useIndex();
  const symbols = useSymbols();
  const [query, setQuery] = useState("");
  const [sideOpen, setSideOpen] = usePersisted("side", true);
  const [rightOpen, setRightOpen] = usePersisted("right", true);
  const sel = parseSelection(params.get("p"));
  const entries = useMemo(() => (index ? entriesOf(index) : []), [index]);
  const env = useMemo<NbEnv>(
    () => ({
      tags: tagCounts(entries).map((t) => t.tag),
      tickers: index?.tickers ?? [],
      symbols: (symbols ?? []).map((s) => s.ticker),
      pages: (index?.pages ?? []).map((p) => ({ slug: p.slug, title: p.title })),
    }),
    [entries, index, symbols],
  );

  // [[A page that does not exist]] and "New page": make the file, then open it
  const making = useRef<string | null>(null);
  const newPage = useCallback(
    async (title: string) => {
      if (making.current === title) return;
      making.current = title;
      try {
        const page = await api.createPage({ title });
        patch((i) => ({ ...i, pages: [page, ...i.pages] }));
        window.location.replace(noteHref(`page:${page.slug}`));
      } finally {
        making.current = null;
      }
    },
    [patch],
  );
  const wantsNew = sel?.kind === "new" ? sel.title : null;
  useEffect(() => {
    if (wantsNew && index) void newPage(wantsNew);
  }, [wantsNew, index, newPage]);

  if (error) return <p className="error">{error}</p>;
  if (!index) return <p className="muted">Loading the notebook…</p>;

  // What is open. On a phone nothing is open until a row is tapped; on a desktop it is Today.
  const open = sel ?? (phone ? null : ({ kind: "today" } as const));
  const day = open?.kind === "today" ? index.today : open?.kind === "day" ? open.date : null;
  const dayNote = day ? index.daily.find((d) => d.date === day) : undefined;
  const todayHasNote = index.daily.some((d) => d.date === index.today);
  let selected: string | null = null;
  let page: React.ReactNode = null;
  let target: Target = { kind: "tag" };
  if (open?.kind === "today" || open?.kind === "day") {
    selected = open.kind === "today" ? "today" : dayNote ? `daily:${dayNote.id}` : null;
    page = <DailyPage key={`${open.kind}:${day}`} note={dayNote} date={day!} index={index} patch={patch} />;
    target = { kind: "day", date: day!, ref: dayNote ? `daily:${dayNote.id}` : null };
  } else if (open?.kind === "daily") {
    const d = index.daily.find((x) => x.id === open.id);
    selected = `daily:${open.id}`;
    page = d ? <DailyPage key={selected} note={d} date={d.date} index={index} patch={patch} /> : <p className="muted">That note is gone.</p>;
    target = { kind: "day", date: d?.date ?? "", ref: selected };
  } else if (open?.kind === "trade") {
    const t = index.trades.find((x) => x.id === open.id);
    selected = `trade:${open.id}`;
    page = t ? <TradePage key={selected} trade={t} patch={patch} /> : <p className="muted">That trade is not in the journal any more.</p>;
    if (t) target = { kind: "trade", trade: t };
  } else if (open?.kind === "stock") {
    selected = `stock:${open.ticker}`;
    page = <StockPage key={selected} ticker={open.ticker} index={index} patch={patch} />;
    target = { kind: "stock", ticker: open.ticker };
  } else if (open?.kind === "page") {
    const p = index.pages.find((x) => x.slug === open.slug);
    selected = `page:${open.slug}`;
    page = p ? (
      <FreePage key={selected} page={p} patch={patch} onGone={() => (window.location.hash = noteHref("today").slice(1))} />
    ) : (
      <p className="muted">That page is gone.</p>
    );
    target = { kind: "page", slug: open.slug, ref: selected };
  } else if (open?.kind === "tag") {
    selected = `tag:${open.tag}`;
    page = <TagView tag={open.tag} entries={entries} />;
  } else if (open?.kind === "new") {
    page = <p className="muted">Making the page…</p>;
  }

  const showSide = phone ? !open : sideOpen;
  const showMain = !phone || !!open;
  const hasRight = open && open.kind !== "tag" && open.kind !== "new";
  const showRight = !!hasRight && (phone ? true : rightOpen);
  const side = (
    <Sidebar
      index={index}
      entries={entries}
      selected={selected}
      query={query}
      onQuery={setQuery}
      todayHasNote={todayHasNote}
      onNewPage={() => void newPage("Untitled")}
    />
  );

  return (
    <NbEnvContext.Provider value={env}>
      <div className={`nb${phone ? " phone" : ""}${showSide ? "" : " no-side"}${showRight ? "" : " no-right"}`}>
        {showSide && <aside className="nb-left">{side}</aside>}
        {showMain && (
          <section className="nb-main" aria-label="Page">
            <div className="nb-bar">
              {phone ? (
                <a className="icon-btn nb-back" href="#/journal/notes" aria-label="Back to the notebook">
                  <Icon name="back" />
                </a>
              ) : (
                <button
                  type="button"
                  className="ghost icon-btn"
                  aria-label={sideOpen ? "Hide the sidebar" : "Show the sidebar"}
                  aria-pressed={sideOpen}
                  onClick={() => setSideOpen(!sideOpen)}
                >
                  <Icon name="table" size={17} />
                </button>
              )}
              <span className="grow" />
              {!phone && hasRight && (
                <button
                  type="button"
                  className="ghost icon-btn"
                  aria-label={rightOpen ? "Hide the side panel" : "Show the side panel"}
                  aria-pressed={rightOpen}
                  onClick={() => setRightOpen(!rightOpen)}
                >
                  <Icon name="chart" size={17} />
                </button>
              )}
            </div>
            <div className="nb-scroll-main">
              <div className="nb-doc">{page}</div>
              {phone && showRight && (
                <div className="nb-right-phone">
                  <RightPanel target={target} index={index} entries={entries} />
                </div>
              )}
            </div>
          </section>
        )}
        {!phone && showRight && (
          <aside className="nb-right" aria-label="Side panel">
            <RightPanel target={target} index={index} entries={entries} />
          </aside>
        )}
      </div>
    </NbEnvContext.Provider>
  );
}
