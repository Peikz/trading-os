// Search that filters as you type (UX round 3, 18 Nov 2026): the tickers of the universe that start
// with the text, then company names that contain it, at most 20 rows; each row is the ticker, the
// company, a grade chip when the stock is a hit today and the list it is on. Up / Down and Enter,
// or a tap, open it on the Chart. Text that matches nothing says "No stock matches". The command
// palette and the Chart's search box share this.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { GradeBadge } from "../components/Card";
import { Icon } from "../ui/Icon";
import { openChart } from "./active";
import { matchSymbols, useSymbols } from "./symbols";

export interface StockRow {
  ticker: string;
  name: string;
  grade: string;
  where: string;
}

/** Grade today and the list a stock is on, for the rows (today's hits, your lists, positions). */
function useStockFacts(): Map<string, { grade: string; where: string }> {
  const [facts, setFacts] = useState<Map<string, { grade: string; where: string }>>(new Map());
  useEffect(() => {
    let live = true;
    Promise.all([api.chartPicks().catch(() => []), api.chartList("hits").catch(() => null)]).then(([picks, hits]) => {
      if (!live) return;
      const out = new Map<string, { grade: string; where: string }>();
      for (const p of Array.isArray(picks) ? picks : []) out.set(p.ticker, { grade: "", where: p.where });
      for (const r of Array.isArray(hits?.rows) ? hits.rows : []) out.set(r.ticker, { grade: r.grade, where: out.get(r.ticker)?.where ?? "Today's hits" });
      setFacts(out);
    });
    return () => {
      live = false;
    };
  }, []);
  return facts;
}

/** The rows for the typed text: `rows` (null until the universe has loaded) and `known`
 * (false when the API has no universe: callers then fall back to opening any ticker). */
export function useStockResults(query: string): { rows: StockRow[]; loaded: boolean; known: boolean } {
  const symbols = useSymbols();
  const facts = useStockFacts();
  const rows = useMemo(
    () =>
      matchSymbols(symbols ?? [], query).map((s) => ({
        ticker: s.ticker,
        name: s.name,
        grade: facts.get(s.ticker)?.grade ?? "",
        where: facts.get(s.ticker)?.where ?? "",
      })),
    [symbols, facts, query],
  );
  return { rows, loaded: symbols !== null, known: (symbols?.length ?? 0) > 0 };
}

export function StockRowView({ row }: { row: StockRow }) {
  return (
    <>
      <b className="sr-tk">{row.ticker}</b>
      <span className="sr-name">{row.name}</span>
      {row.grade && <GradeBadge grade={row.grade} />}
      {row.where && <span className="kind">{row.where}</span>}
    </>
  );
}

/** The Chart's search box: type a ticker or a company name, pick with the arrows or a tap. */
export function StockSearchBox({ className = "" }: { className?: string }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const { rows, known } = useStockResults(query);
  useEffect(() => setIndex(0), [query]);
  useEffect(() => {
    if (!open) return;
    const on = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", on);
    return () => document.removeEventListener("mousedown", on);
  }, [open]);
  const choose = (ticker: string) => {
    openChart(ticker);
    setQuery("");
    setOpen(false);
  };
  const pick = Math.min(index, Math.max(0, rows.length - 1));
  const text = query.trim();
  return (
    <div className={`stock-search ${className}`} ref={box}>
      <label className="list-filter">
        <Icon name="search" size={14} />
        <input
          aria-label="Search a stock"
          role="combobox"
          aria-expanded={open && text !== ""}
          aria-controls="stock-search-list"
          placeholder="Search a stock"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") setIndex((i) => Math.min(i + 1, rows.length - 1));
            else if (e.key === "ArrowUp") setIndex((i) => Math.max(i - 1, 0));
            else if (e.key === "Enter") {
              if (rows[pick]) choose(rows[pick].ticker);
              else if (!known && text) choose(text);
            } else if (e.key === "Escape") {
              setQuery("");
              setOpen(false);
            } else return;
            e.preventDefault();
            e.stopPropagation();
          }}
        />
      </label>
      {open && text !== "" && (
        <ul className="stock-results" id="stock-search-list" role="listbox" aria-label="Stocks">
          {rows.map((r, k) => (
            <li key={r.ticker}>
              <button role="option" aria-selected={k === pick} onMouseEnter={() => setIndex(k)} onClick={() => choose(r.ticker)}>
                <StockRowView row={r} />
              </button>
            </li>
          ))}
          {rows.length === 0 && (
            <li className="empty">{known ? "No stock matches" : `Press Enter to open ${text.toUpperCase()}`}</li>
          )}
        </ul>
      )}
    </div>
  );
}
