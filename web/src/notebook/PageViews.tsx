// The pages of the notebook: a title, a properties row under it (Notion-style) and the body in the
// editor. Four kinds: a day (daily notes), a trade (the grading form's grade, conviction, notes and
// tags), a stock (its notes) and a free page. Each saves by itself a moment after you stop typing,
// through the existing write functions; the only new store is the free pages.
import { type ReactNode, useEffect, useRef, useState } from "react";
import { api, type GradeNote, type NbDaily, type NbIndex, type NbPage, type NbTrade } from "../api";
import { GradeBadge } from "../components/Card";
import { signed, usd } from "../format";
import { stockLink } from "../routes";
import { Icon } from "../ui/Icon";
import { SaveLabel, useAutosave } from "./autosave";
import { Editor } from "./Editor";
import { noteHref, useNbEnv } from "./env";
import { dayTitle, tradeTitle } from "./model";
import { cashtags, hashtags, normalizeTag, withoutTag, withTag } from "./text";

export type Patch = (fn: (i: NbIndex) => NbIndex) => void;

export function Prop({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="nb-prop">
      <span className="nb-k">{label}</span>
      <span className="nb-v">{children}</span>
    </div>
  );
}

/** Tags as chips with an add box; a tag that is only written in the text can be removed from there. */
export function TagsProp({
  tags, onAdd, onRemove, label = "Tags",
}: { tags: string[]; onAdd: (tag: string) => void; onRemove: (tag: string) => void; label?: string }) {
  const env = useNbEnv();
  const [draft, setDraft] = useState("");
  const add = () => {
    const t = normalizeTag(draft);
    if (t) onAdd(t);
    setDraft("");
  };
  const list = `nb-tags-${label}`;
  return (
    <Prop label={label}>
      <span className="nb-chips">
        {tags.map((t) => (
          <span key={t} className="nb-chip">
            <a href={noteHref(`tag:${t}`)}>#{t}</a>
            <button type="button" className="ghost" aria-label={`Remove tag ${t}`} onClick={() => onRemove(t)}>
              <Icon name="x" size={12} />
            </button>
          </span>
        ))}
        <input
          className="nb-tag-input"
          aria-label="Add a tag"
          placeholder="Add tag"
          list={list}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add();
            }
          }}
          onBlur={add}
        />
        <datalist id={list}>
          {env.tags.filter((t) => !tags.includes(t)).map((t) => <option key={t} value={t} />)}
        </datalist>
      </span>
    </Prop>
  );
}

function Stocks({ stocks }: { stocks: string[] }) {
  if (!stocks.length) return <span className="muted">–</span>;
  return (
    <span className="nb-chips">
      {stocks.map((s) => (
        <a key={s} className="nb-chip nb-ticker" href={noteHref(`stock:${s}`)}>${s}</a>
      ))}
    </span>
  );
}

function Shell({
  title, titleNode, props, status, children, actions,
}: {
  title: string;
  titleNode?: ReactNode;
  props: ReactNode;
  status: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <article className="nb-page" aria-label={title}>
      <header className="nb-head">
        <div className="nb-title-row">
          {titleNode ?? <h2 className="nb-h">{title}</h2>}
          <span className="grow" />
          {status}
          {actions}
        </div>
        <div className="nb-props">{props}</div>
      </header>
      <div className="nb-body">{children}</div>
    </article>
  );
}

// --- a day

export function DailyPage({
  note, date, index, patch,
}: { note: NbDaily | undefined; date: string; index: NbIndex; patch: Patch }) {
  const idRef = useRef<string | null>(note?.id ?? null);
  const [text, setText] = useState(note?.text ?? "");
  const [day, setDay] = useState(note?.date ?? date);
  const [editor, setEditor] = useState(0);
  const typed = useRef(note?.stocks ?? []);
  const auto = useAutosave<{ text: string; day: string }>(async ({ text: t, day: d }) => {
    if (!t.trim()) return; // an empty note is not saved: write something, or delete the note
    const stocks = [...new Set([...typed.current, ...cashtags(t)])];
    if (idRef.current) {
      const id = idRef.current;
      await api.editDailyNote(id, { text: t, day: d, tags: typed.current.join(", ") });
      patch((i) => ({ ...i, daily: i.daily.map((x) => (x.id === id ? { ...x, text: t, date: d, stocks, tags: hashtags(t) } : x)) }));
    } else {
      const made = d === index.today ? await api.saveTodayNote(t) : await api.addDailyNote({ text: t, day: d, tags: "" });
      const id = made.note_id;
      if (!id) throw new Error("The note was not saved.");
      idRef.current = id;
      patch((i) => ({ ...i, daily: [{ id, date: d, text: t, stocks, tags: hashtags(t) }, ...i.daily.filter((x) => x.id !== id)] }));
    }
  });
  const change = (t: string) => {
    setText(t);
    auto.push({ text: t, day });
  };
  const setBody = (t: string) => {
    setEditor((n) => n + 1);
    change(t);
  };
  const stocks = [...new Set([...typed.current, ...cashtags(text)])];
  const tags = hashtags(text);
  const remove = async () => {
    if (!idRef.current || !window.confirm("Delete this note? An earlier version stays in the data repo's history.")) return;
    const id = idRef.current;
    await api.removeDailyNote(id);
    patch((i) => ({ ...i, daily: i.daily.filter((x) => x.id !== id) }));
    window.location.hash = noteHref("today");
  };
  return (
    <Shell
      title={dayTitle(day)}
      status={<SaveLabel status={auto.status} error={auto.error} />}
      actions={
        idRef.current ? (
          <button type="button" className="ghost icon-btn" aria-label="Delete this note" onClick={remove}>
            <Icon name="x" size={16} />
          </button>
        ) : null
      }
      props={
        <>
          <Prop label="Date">
            <input
              type="date"
              aria-label="Date"
              value={day}
              onChange={(e) => {
                if (!e.target.value) return;
                setDay(e.target.value);
                auto.push({ text, day: e.target.value });
              }}
            />
          </Prop>
          <Prop label="Stocks"><Stocks stocks={stocks} /></Prop>
          <TagsProp tags={tags} onAdd={(t) => setBody(withTag(text, t))} onRemove={(t) => setBody(withoutTag(text, t))} />
        </>
      }
    >
      <Editor
        key={editor}
        value={text}
        onChange={change}
        imageRef={`day-${day}`}
        label="Note"
        placeholder="How the day went, what you did and why. Type / for commands, #tag, $TICKER."
        autoFocus={editor > 0 || !note}
      />
    </Shell>
  );
}

// --- a trade

const CONVICTION = ["", "1 small", "2 normal", "3 high"];

export function TradePage({ trade, patch }: { trade: NbTrade; patch: Patch }) {
  const [grades, setGrades] = useState<GradeNote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ grade: "", conviction: null as number | null, typed: [] as string[], text: "" });
  const [editor, setEditor] = useState(0);
  useEffect(() => {
    let live = true;
    api.grade("trade", trade.id).then(
      (n) => {
        if (!live) return;
        setGrades(n);
        setForm({ grade: n.grade, conviction: n.conviction, typed: n.tags.split(/[\s,;]+/).map(normalizeTag).filter(Boolean), text: n.notes });
      },
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [trade.id]);
  const auto = useAutosave<typeof form>(async (f) => {
    await api.saveGrade("trade", trade.id, {
      grade: f.grade, notes: f.text, tags: f.typed.join(", "), conviction: f.conviction, screenshots: [],
    });
    const tags = [...new Set([...f.typed, ...hashtags(f.text)])];
    patch((i) => ({
      ...i,
      trades: i.trades.map((t) =>
        t.id === trade.id ? { ...t, grade: f.grade, conviction: f.conviction, text: f.text, tags, typed_tags: f.typed } : t,
      ),
    }));
  });
  if (error) return <p className="error">{error}</p>;
  if (!grades) return <p className="muted">Loading…</p>;
  const update = (next: Partial<typeof form>, remount = false) => {
    const all = { ...form, ...next };
    setForm(all);
    if (remount) setEditor((n) => n + 1);
    auto.push(all);
  };
  const tags = [...new Set([...form.typed, ...hashtags(form.text)])];
  const r = trade.r;
  return (
    <Shell
      title={tradeTitle(trade)}
      titleNode={
        <h2 className="nb-h">
          <a href={stockLink(trade.ticker)} title="Open the chart">{trade.ticker}</a>
          <span className="nb-h-sub">{trade.setup || "trade"} · {trade.status}</span>
        </h2>
      }
      status={<SaveLabel status={auto.status} error={auto.error} />}
      props={
        <>
          <Prop label="Date">{trade.entry_date ?? "–"}{trade.exit_date ? ` → ${trade.exit_date}` : ""}</Prop>
          <Prop label="Ticker"><Stocks stocks={[trade.ticker]} /></Prop>
          <Prop label="Setup">{trade.setup || <span className="muted">–</span>}</Prop>
          <Prop label="Grade">
            <select aria-label="Grade" value={form.grade} onChange={(e) => update({ grade: e.target.value })}>
              {grades.grades.map((g) => <option key={g || "none"} value={g}>{g || "none"}</option>)}
            </select>
            {form.grade && <GradeBadge grade={form.grade} />}
          </Prop>
          <Prop label="Conviction">
            <select
              aria-label="Conviction"
              value={form.conviction ?? ""}
              onChange={(e) => update({ conviction: e.target.value ? Number(e.target.value) : null })}
            >
              {CONVICTION.map((c, n) => <option key={c || "none"} value={n || ""}>{c || "none"}</option>)}
            </select>
          </Prop>
          <Prop label="R">
            {r === null ? <span className="muted">–</span> : <span className={r >= 0 ? "up" : "down"}>{signed(r, 2, "R")}</span>}
            {trade.pnl !== null && <span className="muted"> {usd(trade.pnl)}</span>}
          </Prop>
          <Prop label="Status">{trade.status === "open" ? "Open" : "Closed"}</Prop>
          <TagsProp
            tags={tags}
            onAdd={(t) => update({ typed: [...new Set([...form.typed, t])] })}
            onRemove={(t) =>
              form.typed.includes(t)
                ? update({ typed: form.typed.filter((x) => x !== t) })
                : update({ text: withoutTag(form.text, t) }, true)
            }
          />
        </>
      }
    >
      <Editor
        key={editor}
        value={form.text}
        onChange={(t) => update({ text: t })}
        imageRef={trade.id}
        label="Trade notes"
        placeholder="Why you took it, how you managed it, what you would change. Type / for commands."
      />
      {grades.attachments.length > 0 && (
        <div className="shots" aria-label="Screenshots from the grading form">
          {grades.attachments.map((a) => <img key={a} src={`/api/attachments/${a}`} alt={a.split("/").pop()} />)}
        </div>
      )}
    </Shell>
  );
}

// --- a stock

function StockNoteBlock({
  ticker, id, date, text, patch, onCreated,
}: { ticker: string; id: string | null; date: string; text: string; patch: Patch; onCreated?: (id: string) => void }) {
  const idRef = useRef<string | null>(id);
  const [gone, setGone] = useState(false);
  const auto = useAutosave<string>(async (t) => {
    if (!t.trim()) return;
    const tags = hashtags(t);
    if (idRef.current) {
      const nid = idRef.current;
      await api.editChartNote(ticker, nid, t, date);
      patch((i) => ({
        ...i,
        stocks: i.stocks.map((s) => (s.ticker === ticker ? { ...s, notes: s.notes.map((n) => (n.note_id === nid ? { ...n, text: t, tags } : n)) } : s)),
      }));
    } else {
      const made = await api.addChartNote(ticker, t, date);
      idRef.current = made.note_id;
      onCreated?.(made.note_id);
      const row = { note_id: made.note_id, date, text: t, tags };
      patch((i) => ({
        ...i,
        stocks: i.stocks.some((s) => s.ticker === ticker)
          ? i.stocks.map((s) => (s.ticker === ticker ? { ...s, notes: [row, ...s.notes] } : s))
          : [...i.stocks, { ticker, notes: [row], tags }].sort((a, b) => a.ticker.localeCompare(b.ticker)),
      }));
    }
  });
  if (gone) return null;
  return (
    <section className="nb-stock-note" aria-label={`Note of ${date}`}>
      <div className="nb-note-head">
        <span className="nb-k">{date}</span>
        <span className="grow" />
        <SaveLabel status={auto.status} error={auto.error} />
        {idRef.current && (
          <button
            type="button"
            className="ghost icon-btn"
            aria-label={`Delete the note of ${date}`}
            onClick={async () => {
              if (!window.confirm("Delete this note?")) return;
              const nid = idRef.current!;
              await api.removeChartNote(ticker, nid);
              patch((i) => ({ ...i, stocks: i.stocks.map((s) => (s.ticker === ticker ? { ...s, notes: s.notes.filter((n) => n.note_id !== nid) } : s)) }));
              setGone(true);
            }}
          >
            <Icon name="x" size={14} />
          </button>
        )}
      </div>
      <Editor
        value={text}
        onChange={(t) => auto.push(t)}
        imageRef={ticker}
        label={`Note on ${ticker} of ${date}`}
        placeholder={id ? undefined : "A note on this stock. Type / for commands."}
        autoFocus={!id}
      />
    </section>
  );
}

export function StockPage({ ticker, index, patch }: { ticker: string; index: NbIndex; patch: Patch }) {
  const stock = index.stocks.find((s) => s.ticker === ticker);
  // Notes written on this visit stay in their own blocks (newest on top); the saved ones follow
  const [blocks, setBlocks] = useState<number[]>([0]);
  const [mine, setMine] = useState<string[]>([]);
  const all = stock?.notes ?? [];
  const notes = all.filter((n) => !mine.includes(n.note_id));
  const tags = [...new Set(all.flatMap((n) => n.tags))];
  const trades = index.trades.filter((t) => t.ticker === ticker);
  return (
    <Shell
      title={`$${ticker}`}
      titleNode={
        <h2 className="nb-h">
          <a href={stockLink(ticker)} title="Open the chart">${ticker}</a>
        </h2>
      }
      status={null}
      props={
        <>
          <Prop label="Notes">{all.length}</Prop>
          <Prop label="Trades">
            {trades.length === 0 ? <span className="muted">–</span> : (
              <span className="nb-chips">
                {trades.slice(0, 6).map((t) => (
                  <a key={t.id} className="nb-chip" href={noteHref(`trade:${t.id}`)}>{t.entry_date?.slice(5)}</a>
                ))}
              </span>
            )}
          </Prop>
          <Prop label="Tags">
            {tags.length === 0 ? <span className="muted">–</span> : (
              <span className="nb-chips">{tags.map((t) => <a key={t} className="nb-chip" href={noteHref(`tag:${t}`)}>#{t}</a>)}</span>
            )}
          </Prop>
        </>
      }
    >
      {[...blocks].reverse().map((k) => (
        <StockNoteBlock
          key={`new-${k}`}
          ticker={ticker}
          id={null}
          date={index.today}
          text=""
          patch={patch}
          onCreated={(id) => setMine((m) => [...m, id])}
        />
      ))}
      <button type="button" className="link nb-another" onClick={() => setBlocks((b) => [...b, b.length])}>
        + Another note
      </button>
      {notes.map((n) => (
        <StockNoteBlock key={n.note_id} ticker={ticker} id={n.note_id} date={n.date} text={n.text} patch={patch} />
      ))}
    </Shell>
  );
}

// --- a free page

export function FreePage({ page, patch, onGone }: { page: NbPage; patch: Patch; onGone: () => void }) {
  const [title, setTitle] = useState(page.title);
  const [text, setText] = useState(page.text);
  const [typed, setTyped] = useState(page.typed_tags);
  const [editor, setEditor] = useState(0);
  const auto = useAutosave<{ title: string; text: string; typed: string[] }>(async (v) => {
    const saved = await api.savePage(page.slug, { title: v.title, text: v.text, tags: v.typed });
    patch((i) => ({ ...i, pages: i.pages.map((p) => (p.slug === page.slug ? saved : p)) }));
  });
  const push = (next: Partial<{ title: string; text: string; typed: string[] }>, remount = false) => {
    const all = { title, text, typed, ...next };
    if (next.title !== undefined) setTitle(next.title);
    if (next.text !== undefined) setText(next.text);
    if (next.typed !== undefined) setTyped(next.typed);
    if (remount) setEditor((n) => n + 1);
    auto.push(all);
  };
  const tags = [...new Set([...typed, ...hashtags(text)])];
  return (
    <Shell
      title={title}
      titleNode={
        <input
          className="nb-title-input"
          aria-label="Page title"
          value={title}
          placeholder="Untitled"
          onChange={(e) => push({ title: e.target.value })}
        />
      }
      status={<SaveLabel status={auto.status} error={auto.error} />}
      actions={
        <button
          type="button"
          className="ghost icon-btn"
          aria-label="Delete this page"
          onClick={async () => {
            if (!window.confirm(`Delete the page “${title}”? Its file is removed from the data repo.`)) return;
            await api.deletePage(page.slug);
            patch((i) => ({ ...i, pages: i.pages.filter((p) => p.slug !== page.slug) }));
            onGone();
          }}
        >
          <Icon name="x" size={16} />
        </button>
      }
      props={
        <>
          <Prop label="Created">{page.created}</Prop>
          <TagsProp
            tags={tags}
            onAdd={(t) => push({ typed: [...new Set([...typed, t])] })}
            onRemove={(t) => (typed.includes(t) ? push({ typed: typed.filter((x) => x !== t) }) : push({ text: withoutTag(text, t) }, true))}
          />
        </>
      }
    >
      <Editor
        key={editor}
        value={text}
        onChange={(t) => push({ text: t })}
        imageRef={`page-${page.slug}`}
        label="Page"
        placeholder="Start writing. Type / for commands, #tag, $TICKER, [[Page]]."
        autoFocus={!page.text && editor === 0}
      />
    </Shell>
  );
}
