// Ctrl+K, "/" or typing a letter outside a field: jump to any stock (today's hits, your
// watchlists and positions first, or any ticker you type), any place or tab, or run Pull latest
// / Save & push. Enter on an exact ticker opens it on the Chart.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { hrefFor, PLACES, TABS } from "../routes";
import { openChart } from "./active";
import { Icon } from "../ui/Icon";

interface Item {
  id: string;
  label: string;
  kind: string;
  icon: string;
  run: () => void;
}

const TICKERish = /^\$?[A-Za-z][A-Za-z0-9.-]{0,9}$/;

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

  useEffect(() => {
    input.current?.focus();
    api.chartPicks().then(setPicks, () => setPicks([]));
  }, []);

  const items = useMemo(() => {
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
    const stocks: Item[] = picks.map((p) => ({
      id: `s-${p.ticker}`,
      label: p.ticker,
      kind: p.where,
      icon: "stocks",
      run: () => {
        openChart(p.ticker);
        onClose();
      },
    }));
    const match = (i: Item) => !q || i.label.toLowerCase().includes(q) || i.kind.toLowerCase().includes(q);
    // An exact ticker comes before the other stocks that merely contain the letters
    const exact = (i: Item) => (i.label.toLowerCase() === q ? 0 : 1);
    const found = stocks.filter(match).sort((a, b) => exact(a) - exact(b));
    const out = [...found, ...pages.filter(match), ...actions.filter(match)];
    if (q && TICKERish.test(query.trim())) {
      const t = query.trim().replace(/^\$/, "").toUpperCase();
      if (!out.some((i) => i.id === `s-${t}`)) {
        // A typed ticker comes first, unless the words name a page or tab
        const named = pages.some(match);
        out.splice(named ? out.length : 0, 0, { id: `s-${t}`, label: t, kind: "Open the chart", icon: "stocks", run: () => { openChart(t); onClose(); } });
      }
    }
    return q ? out : out.slice(0, 14);
  }, [query, picks, onClose, onPull, onPush]);

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
            placeholder="A ticker, a page or a tab…"
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
        {items.length === 0 ? (
          <p className="empty">Nothing matches. Type a ticker to open its chart.</p>
        ) : (
          <ul role="listbox" aria-label="Results">
            {items.map((i, k) => (
              <li key={i.id}>
                <button role="option" aria-selected={k === pick} onMouseEnter={() => setIndex(k)} onClick={i.run}>
                  <Icon name={i.icon} size={16} />
                  <b>{i.label}</b>
                  <span className="kind">{i.kind}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
