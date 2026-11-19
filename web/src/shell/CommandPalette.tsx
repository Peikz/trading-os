// Ctrl+K, "/" or typing a letter outside a field: jump to any stock, any place or tab, or run Pull
// latest / Save & push. Typing filters live: the universe's tickers that start with the text, then
// company names that contain it (at most 20), each with its grade if it is a hit today and the
// list it is on; Up / Down and Enter or a tap open it on the Chart. Text that matches no stock says
// so. Pages and tabs match by their words below the stocks.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { hrefFor, PLACES, TABS } from "../routes";
import { openChart } from "./active";
import { StockRowView, type StockRow, useStockResults } from "./stockSearch";
import { Icon } from "../ui/Icon";

interface Item {
  id: string;
  label: string;
  kind: string;
  icon: string;
  run: () => void;
  stock?: StockRow;
}


export function CommandPalette({
  onClose,
  onPull,
  onPush,
  initial = "",
}: {
  initial?: string;
  onClose: () => void;
  onPull: () => void;
  onPush: () => void;
}) {
  const [query, setQuery] = useState(initial);
  const [picks, setPicks] = useState<{ ticker: string; where: string }[]>([]);
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const found = useStockResults(query);

  useEffect(() => {
    input.current?.focus();
    api.chartPicks().then(setPicks, () => setPicks([]));
  }, []);

  const { items, noStock } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const open = (href: string) => () => {
      window.location.hash = href;
      onClose();
    };
    const pages: Item[] = PLACES.flatMap((p) => [
      { id: `p-${p.id}`, label: p.label, kind: p.question, icon: p.icon, run: open(hrefFor(p.id)) },
      ...TABS[p.id].map(([tab, text]) => ({
        id: `p-${p.id}-${tab}`,
        label: `${p.label} · ${text}`,
        kind: "Tab",
        icon: p.icon,
        run: open(hrefFor(p.id, tab)),
      })),
    ]);
    const actions: Item[] = [
      { id: "a-pull", label: "Pull latest", kind: "Sync", icon: "refresh", run: () => { onPull(); onClose(); } },
      { id: "a-push", label: "Save & push", kind: "Sync", icon: "upload", run: () => { onPush(); onClose(); } },
    ];
    const stock = (t: string, kind: string, row?: StockRow): Item => ({
      id: `s-${t}`,
      label: t,
      kind,
      icon: "stocks",
      stock: row,
      run: () => {
        openChart(t);
        onClose();
      },
    });
    const match = (i: Item) => !q || i.label.toLowerCase().includes(q) || i.kind.toLowerCase().includes(q);
    let stocks: Item[];
    if (!q) {
      stocks = picks.map((p) => stock(p.ticker, p.where));
    } else if (found.known) {
      stocks = found.rows.map((r) => stock(r.ticker, r.where, r));
    } else {
      // Only stocks that exist (owner, 19 Nov 2026): without the universe, only your own picks that
      // match the text; a typed ticker is never opened on trust.
      stocks = picks.map((p) => stock(p.ticker, p.where)).filter(match);
    }
    const out = [...stocks, ...pages.filter(match), ...actions.filter(match)];
    return { items: q ? out : out.slice(0, 14), noStock: !!q && found.loaded && !stocks.length };
  }, [query, picks, found, onClose, onPull, onPush]);

  useEffect(() => setIndex(0), [query]);
  const pick = Math.min(index, Math.max(0, items.length - 1));

  return (
    <div
      className="palette-back"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="palette" role="dialog" aria-label="Search">
        <div className="palette-input">
          <Icon name="search" />
          <input
            ref={input}
            aria-label="Search stocks, pages and tabs"
            placeholder="A ticker, a company, a page or a tab…"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") setIndex((i) => Math.min(i + 1, items.length - 1));
              else if (e.key === "ArrowUp") setIndex((i) => Math.max(i - 1, 0));
              else if (e.key === "Enter") items[pick]?.run();
              else if (e.key === "Escape") onClose();
              else return;
              e.preventDefault();
            }}
          />
          <kbd>Esc</kbd>
        </div>
        {noStock && <p className="empty no-stock">No stock matches</p>}
        {items.length === 0 ? (
          !noStock && <p className="empty">Nothing matches.</p>
        ) : (
          <ul role="listbox" aria-label="Results">
            {items.map((i, k) => (
              <li key={i.id}>
                <button role="option" aria-selected={k === pick} onMouseEnter={() => setIndex(k)} onClick={i.run}>
                  {i.stock ? (
                    <StockRowView row={i.stock} />
                  ) : (
                    <>
                      <Icon name={i.icon} size={16} />
                      <b>{i.label}</b>
                      <span className="kind">{i.kind}</span>
                    </>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
