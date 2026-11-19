// The Chart's one "Notes" tab (round 4, the owner, 19 Nov 2026): the stock's notebook page, in the
// Chart. It replaces the two old tabs, Notes and Journal, which were two places for the same stock.
// Here: an "Open in Journal" link to the same page in the notebook, the stock's notes (live
// preview, #tags, $tickers, saved by themselves; a new note is written right here), the daily notes
// that mention it, its trades with R, grade and conviction (each opens in the notebook), and the
// grading form when the stock is a scan hit today. Everything the old tabs could show or save is here.
import { useEffect, useState } from "react";
import { api, type ChartListRow, type ChartNotes, type NbIndex } from "../../api";
import { GradeBadge } from "../../components/Card";
import { Table } from "../../components/Table";
import { signed, usd } from "../../format";
import { noteHref, NbEnvContext } from "../../notebook/env";
import { useIndex, useNbEnvOf } from "../../notebook/Notebook";
import { StockNoteBlock } from "../../notebook/PageViews";
import { snippet } from "../../notebook/text";
import { HitGrading } from "../../pages/Screener";
import { Icon } from "../../ui/Icon";

const CONVICTION = ["", "small", "normal", "high"];

export function NotesTab({ symbol, row }: { symbol: string; row: ChartListRow | undefined }) {
  const { index, error, patch } = useIndex();
  const env = useNbEnvOf(index);
  // When each note was written and last edited (the notebook's index has only its day)
  const [stamps, setStamps] = useState<ChartNotes | null>(null);
  useEffect(() => {
    let live = true;
    setStamps(null);
    api.chartNotes(symbol).then((n) => live && setStamps(n), () => live && setStamps(null));
    return () => {
      live = false;
    };
  }, [symbol]);
  if (error) return <p className="error">{error}</p>;
  if (!index) return <p className="muted">Loading the notes…</p>;
  return (
    <NbEnvContext.Provider value={env}>
      <StockNotes symbol={symbol} index={index} patch={patch} stamps={stamps} row={row} />
    </NbEnvContext.Provider>
  );
}

function StockNotes({
  symbol,
  index,
  patch,
  stamps,
  row,
}: {
  symbol: string;
  index: NbIndex;
  patch: (fn: (i: NbIndex) => NbIndex) => void;
  stamps: ChartNotes | null;
  row: ChartListRow | undefined;
}) {
  const stock = index.stocks.find((s) => s.ticker === symbol);
  const notes = stock?.notes ?? [];
  const trades = index.trades.filter((t) => t.ticker === symbol);
  const days = index.daily.filter((d) => d.stocks.includes(symbol));
  // Notes written on this visit stay in their own blocks (newest on top); the saved ones follow
  const [fresh, setFresh] = useState<number[]>([0]);
  const [mine, setMine] = useState<string[]>([]);
  useEffect(() => {
    setFresh([0]);
    setMine([]);
  }, [symbol]);
  const meta = (id: string) => {
    const s = stamps?.notes.find((n) => n.note_id === id);
    return s ? `written ${s.written ?? "?"}${s.edited ? ` · edited ${s.edited}` : ""}` : undefined;
  };
  return (
    <div className="notes-tab">
      <div className="notes-top">
        <b>Notes on {symbol}</b>
        <span className="muted">
          {notes.length} {notes.length === 1 ? "note" : "notes"} · {trades.length} {trades.length === 1 ? "trade" : "trades"}
        </span>
        <span className="grow" />
        <a href={noteHref(`stock:${symbol}`)} className="open-journal">
          Open in Journal
        </a>
      </div>
      {[...fresh].reverse().map((k) => (
        <StockNoteBlock
          key={`${symbol}-new-${k}`}
          ticker={symbol}
          id={null}
          date={index.today}
          text=""
          patch={patch}
          autoFocus={false}
          onCreated={(id) => setMine((m) => [...m, id])}
        />
      ))}
      <button type="button" className="link nb-another" onClick={() => setFresh((b) => [...b, b.length])}>
        + Another note
      </button>
      {notes
        .filter((n) => !mine.includes(n.note_id))
        .map((n) => (
          <StockNoteBlock key={`${symbol}-${n.note_id}`} ticker={symbol} id={n.note_id} date={n.date} text={n.text} patch={patch} meta={meta(n.note_id)} />
        ))}
      {days.length > 0 && (
        <section aria-label="From your daily notes">
          <h3 className="nb-side-h">From your daily notes ({days.length})</h3>
          {days.map((d) => (
            <a key={d.id} className="nb-hit" href={noteHref(`daily:${d.id}`)}>
              <span className="nb-hit-top">
                <b>{d.date}</b>
                <span className="nb-kind">Day</span>
              </span>
              <span className="nb-snip nb-hit-snip">{snippet(d.text, 200)}</span>
            </a>
          ))}
        </section>
      )}
      <section aria-label={`Trades in ${symbol}`}>
        <h3 className="nb-side-h">Trades in {symbol}</h3>
        {trades.length === 0 ? (
          <p className="muted">No trades in {symbol} yet.</p>
        ) : (
          <Table
            label={`Trades in ${symbol}`}
            columns={["entry_date", "exit_date", "setup", "r", "pnl", "grade", "conviction", " "]}
            headers={{ entry_date: "Entry", exit_date: "Exit", setup: "Setup", r: "R", pnl: "P&L", grade: "Grade", conviction: "Conviction", " ": "" }}
            rows={trades.map((t) => ({
              id: t.id, entry_date: t.entry_date, exit_date: t.status === "open" ? "open" : t.exit_date,
              setup: t.setup, r: t.r, pnl: t.pnl, grade: t.grade, conviction: t.conviction,
            }))}
            render={(c, t) => {
              if (c === "r") return t.r === null ? "–" : <span className={`num ${(t.r as number) >= 0 ? "up" : "down"}`}>{signed(t.r as number, 2, "R")}</span>;
              if (c === "pnl") return t.pnl === null ? "–" : usd(t.pnl as number);
              if (c === "grade") return t.grade ? <GradeBadge grade={String(t.grade)} /> : <span className="muted">–</span>;
              if (c === "conviction") return t.conviction ? `${t.conviction} ${CONVICTION[Number(t.conviction)] ?? ""}` : "–";
              if (c === " ")
                return (
                  <a href={noteHref(`trade:${t.id}`)} aria-label={`Open the ${t.entry_date} trade in the notebook`}>
                    Open <Icon name="right" size={12} />
                  </a>
                );
              return undefined;
            }}
          />
        )}
      </section>
      {row?.signal_id && <HitGrading ticker={symbol} signalId={row.signal_id} scanLabel={row.setup} />}
    </div>
  );
}
