// Watchlists (UX round 3, 18 Nov 2026, the owner's approved mockup): a place of its own. Left rail:
// My lists (+ New list), From the scans (EP-Watch, BO-Watch) and Alerts (price alerts, with what
// fired today). Main: the list's name and count, Add tickers, Import .txt, Export, and a table
// with a checkbox, ticker, last, change, 20-day chart, RVOL, what it is today (hit and grade),
// note and added date. Selecting rows brings a bar: Clear, Remove selected, Open as Chart list.
// On a phone: list chips on top, 56 px rows, swipe a row left to remove it, long-press to select.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ChartListRow, type WatchList } from "../api";
import { GradeBadge } from "../components/Card";
import { download, readText } from "../format";
import { PriceAlerts, ScanLists } from "../pages/Watchlists";
import { Sparkline } from "./chart/WatchPanel";
import { useSparks } from "./chart/lists";
import { hrefFor } from "../routes";
import { openChart } from "../shell/active";
import { nameOf, useNames } from "../shell/symbols";
import { Icon } from "../ui/Icon";
import { PHONE, useMedia, usePopover } from "../ui/kit";

type Pick = { kind: "list"; name: string } | { kind: "scan"; id: string; label: string } | { kind: "alerts" };

const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const pct = (x: number | null) => (x === null ? "–" : `${x >= 0 ? "+" : ""}${x.toFixed(1)}%`);
const dir = (x: number | null) => (x === null ? "" : x >= 0 ? "up" : "down");
const added = (v: unknown) => {
  if (typeof v !== "string" || !v) return "";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v.slice(0, 10) : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
};

function csvOf(list: WatchList): string {
  const cols = list.columns.filter((c) => c !== "exchange");
  const q = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return [cols.join(","), ...list.rows.map((r) => cols.map((c) => q(r[c])).join(","))].join("\n");
}

export function Watchlists({ params }: { params: URLSearchParams }) {
  const phone = useMedia(PHONE);
  const [names, setNames] = useState<string[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [scanCounts, setScanCounts] = useState<Record<string, number>>({});
  const [alertCount, setAlertCount] = useState<number | null>(null);
  const [pick, setPick] = useState<Pick | null>(null);
  const [creating, setCreating] = useState(false);
  const [version, setVersion] = useState(0);

  const loadNames = useCallback(
    () =>
      api.watchlists().then(
        (w) => {
          setNames(w.lists);
          Promise.all(w.lists.map((n) => api.watchlist(n).then((l) => [n, l.rows.length] as const, () => [n, 0] as const))).then((e) =>
            setCounts(Object.fromEntries(e)),
          );
        },
        () => setNames([]),
      ),
    [],
  );
  useEffect(() => {
    loadNames();
    api.scanWatchlists(false).then(
      (d) => setScanCounts(Object.fromEntries(Object.entries(d).map(([id, w]) => [id, w.rows.length]))),
      () => {},
    );
    api.alerts().then((a) => setAlertCount(a.alerts.length), () => setAlertCount(null));
  }, [loadNames, version]);

  // The list in the address (?list=Name) or the first one
  const wanted = params.get("list");
  useEffect(() => {
    if (pick || names === null) return;
    if (wanted && names.includes(wanted)) setPick({ kind: "list", name: wanted });
    else if (names.length) setPick({ kind: "list", name: names[0] });
    else setCreating(true);
  }, [names, pick, wanted]);

  const choose = (p: Pick) => {
    setCreating(false);
    setPick(p);
  };
  const is = (p: Pick) => JSON.stringify(p) === JSON.stringify(pick) && !creating;

  const rail = (
    <nav className="wl-rail" aria-label="Lists">
      <div className="section-label">My lists</div>
      {(names ?? []).map((n) => (
        <button key={n} className="rail-item" aria-current={is({ kind: "list", name: n })} onClick={() => choose({ kind: "list", name: n })}>
          <span>{n}</span>
          <span className="muted num">{counts[n] ?? ""}</span>
        </button>
      ))}
      <button className="rail-item add" aria-current={creating} onClick={() => setCreating(true)}>
        + New list
      </button>
      <div className="section-label">From the scans</div>
      {[["ep_watch", "EP-Watch"], ["bo_watch", "BO-Watch"]].map(([id, label]) => (
        <button key={id} className="rail-item" aria-current={is({ kind: "scan", id, label })} onClick={() => choose({ kind: "scan", id, label })}>
          <span>{label}</span>
          <span className="muted num">{scanCounts[id] ?? ""}</span>
        </button>
      ))}
      <div className="section-label">Alerts</div>
      <button className="rail-item" aria-current={is({ kind: "alerts" })} onClick={() => choose({ kind: "alerts" })}>
        <span>Price alerts</span>
        <span className="muted num">{alertCount ?? ""}</span>
      </button>
    </nav>
  );

  const chips = (
    <div className="chip-row" role="group" aria-label="Lists">
      {(names ?? []).map((n) => (
        <button key={n} className="pick-chip" aria-pressed={is({ kind: "list", name: n })} onClick={() => choose({ kind: "list", name: n })}>
          {n} <span className="num">{counts[n] ?? ""}</span>
        </button>
      ))}
      {[["ep_watch", "EP-Watch"], ["bo_watch", "BO-Watch"]].map(([id, label]) => (
        <button key={id} className="pick-chip" aria-pressed={is({ kind: "scan", id, label })} onClick={() => choose({ kind: "scan", id, label })}>
          {label} <span className="num">{scanCounts[id] ?? ""}</span>
        </button>
      ))}
      <button className="pick-chip" aria-pressed={is({ kind: "alerts" })} onClick={() => choose({ kind: "alerts" })}>
        Alerts <span className="num">{alertCount ?? ""}</span>
      </button>
    </div>
  );

  const main = creating ? (
    <NewList
      onCreated={(name) => {
        setCreating(false);
        setPick({ kind: "list", name });
        setVersion((v) => v + 1);
      }}
    />
  ) : pick?.kind === "list" ? (
    <ListView key={pick.name} name={pick.name} phone={phone} onChanged={() => setVersion((v) => v + 1)} />
  ) : pick?.kind === "scan" ? (
    <div className="wl-main-pad">
      <h2>{pick.label}</h2>
      <ScanLists only={pick.id} />
    </div>
  ) : pick?.kind === "alerts" ? (
    <div className="wl-main-pad">
      <h2>Price alerts</h2>
      <p className="muted">Alerts fire once when the price is crossed.</p>
      <PriceAlerts />
    </div>
  ) : (
    <p className="muted wl-main-pad">Loading…</p>
  );

  return (
    <div className="wl-place">
      <h1 className="sr-only">Watchlists</h1>
      {phone && (
        <div className="phone-head">
          <span className="phone-title">Watchlists</span>
          <button className="ghost icon-btn big" aria-label="New list" onClick={() => setCreating(true)}>
            <Icon name="plus" size={22} />
          </button>
        </div>
      )}
      {phone ? chips : rail}
      <section className="wl-main" aria-label="List">
        {main}
      </section>
    </div>
  );
}

function NewList({ onCreated }: { onCreated: (name: string) => void }) {
  const [name, setName] = useState("");
  const [typed, setTyped] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const create = () =>
    api.addToWatchlist(name.trim(), typed, "", "").then(
      (r) => (r.added.length ? onCreated(name.trim()) : setMsg(r.lines.join(" ").replace(/\*\*/g, "") || "Add at least one ticker.")),
      (e: Error) => setMsg(e.message),
    );
  return (
    <div className="wl-main-pad" aria-label="New list">
      <h2>New list</h2>
      <div className="row">
        <input aria-label="New list name" placeholder="Name of the list" value={name} onChange={(e) => setName(e.target.value)} />
        <input aria-label="First tickers" placeholder="First tickers, e.g. ABCD, EFGH" value={typed} onChange={(e) => setTyped(e.target.value)} />
        <button className="primary" disabled={!name.trim() || !typed.trim()} onClick={create}>
          Create
        </button>
      </div>
      {msg && <p className="error">{msg}</p>}
      <p className="muted hint">Saved in the data repo; it is pushed to GitHub with your other changes.</p>
    </div>
  );
}

function useHitGrades(): Record<string, ChartListRow> {
  const [m, setM] = useState<Record<string, ChartListRow>>({});
  useEffect(() => {
    api.chartList("hits").then((l) => setM(Object.fromEntries(l.rows.map((r) => [r.ticker, r]))), () => setM({}));
  }, []);
  return m;
}

function ListView({ name, phone, onChanged }: { name: string; phone: boolean; onChanged: () => void }) {
  const [list, setList] = useState<WatchList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [version, setVersion] = useState(0);
  const hits = useHitGrades();
  useNames();
  const file = useRef<HTMLInputElement>(null);
  const exportMenu = usePopover();

  useEffect(() => {
    api.watchlist(name).then(setList, (e: Error) => setError(e.message));
  }, [name, version]);
  const rows = useMemo(() => list?.rows ?? [], [list]);
  const sparks = useSparks(rows.map((r) => String(r.ticker)));
  const changed = () => {
    setVersion((v) => v + 1);
    onChanged();
  };
  const add = async (text: string, exportText = "") => {
    try {
      const out = await api.addToWatchlist(name, text, exportText, "");
      setMsg(out.lines.join(" ").replace(/\*\*/g, ""));
      if (out.added.length) {
        setTyped("");
        changed();
      }
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  const remove = (tickers: string[]) =>
    api.removeFromWatchlist(name, tickers).then(
      () => {
        setPicked(new Set());
        changed();
      },
      (e: Error) => setMsg(e.message),
    );
  const toggle = (t: string) =>
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(t)) n.delete(t);
      else n.add(t);
      return n;
    });
  const openAsList = () => {
    const first = [...picked][0] ?? (rows[0] ? String(rows[0].ticker) : "");
    if (first) openChart(first, `wl:${name}`);
  };

  if (error) return <p className="error wl-main-pad">{error}</p>;

  const head = (
    <div className="wl-head">
      <span className="wl-title">{name}</span>
      <span className="muted">{list === null ? "Loading…" : `${rows.length} ${rows.length === 1 ? "stock" : "stocks"}`}</span>
      <span className="grow" />
      {!phone && (
        <>
          <input
            aria-label="Add tickers"
            placeholder="Add tickers, e.g. ABCD, EFGH"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && typed.trim() && add(typed)}
          />
          <button className="primary" disabled={!typed.trim()} onClick={() => add(typed)}>
            Add
          </button>
          <input
            ref={file}
            type="file"
            accept=".txt"
            aria-label="Import .txt"
            hidden
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) await add("", await readText(f));
              e.target.value = "";
            }}
          />
          <button onClick={() => file.current?.click()}>Import .txt</button>
          <div className="popover-wrap" ref={exportMenu.ref}>
            <button aria-expanded={exportMenu.open} onClick={() => exportMenu.setOpen(!exportMenu.open)} disabled={!list}>
              Export
              <Icon name="down" size={14} />
            </button>
            {exportMenu.open && list && (
              <div className="popover menu" role="menu" aria-label="Export">
                <button role="menuitem" onClick={() => { download(`${name}.txt`, list.tv_list); exportMenu.setOpen(false); }}>
                  TradingView list (.txt)
                </button>
                <button role="menuitem" onClick={() => { download(`${name}.csv`, csvOf(list)); exportMenu.setOpen(false); }}>
                  CSV
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
  const bar = picked.size > 0 && (
    <div className="select-bar" role="status">
      <span>{picked.size} selected</span>
      <button onClick={() => setPicked(new Set())}>Clear</button>
      <button className="danger" onClick={() => remove([...picked])}>
        Remove selected
      </button>
      <button onClick={openAsList}>Open as Chart list</button>
    </div>
  );

  if (phone) {
    return (
      <>
        {head}
        <div className="phone-add">
          <input aria-label="Add tickers" placeholder="Add tickers" value={typed} onChange={(e) => setTyped(e.target.value)} />
          <button className="primary" disabled={!typed.trim()} onClick={() => add(typed)}>
            Add
          </button>
        </div>
        {msg && <p className="muted wl-main-pad">{msg}</p>}
        {bar}
        <ul className="plist" aria-label={`Watchlist ${name}`}>
          {rows.map((r) => {
            const t = String(r.ticker);
            return (
              <SwipeRow
                key={t}
                selecting={picked.size > 0}
                selected={picked.has(t)}
                onToggle={() => toggle(t)}
                onOpen={() => openChart(t, `wl:${name}`)}
                onRemove={() => remove([t])}
              >
                <span className="pl-main">
                  <b>{t}</b>
                  <small className="muted">
                    {[nameOf(t), hits[t]?.grade && `${hits[t].grade} hit`, typeof r.note === "string" && r.note].filter(Boolean).join(" · ")}
                  </small>
                </span>
                <Sparkline closes={sparks[t]} />
                <span className="pl-num">
                  <span className="num">{num(r.close)?.toFixed(2) ?? "–"}</span>
                  <span className={`num ${dir(num(r.chg_pct))}`}>{pct(num(r.chg_pct))}</span>
                </span>
              </SwipeRow>
            );
          })}
        </ul>
        {list !== null && rows.length === 0 && <p className="muted wl-main-pad">No stocks in this list yet.</p>}
        <p className="muted hint wl-main-pad">Swipe a row left to remove it. Long-press to select several.</p>
      </>
    );
  }

  return (
    <>
      {head}
      {msg && <p className="muted wl-main-pad">{msg}</p>}
      {bar}
      <div className="dtable-wrap">
        <table className="dtable" aria-label={`Watchlist ${name}`}>
          <thead>
            <tr>
              <th className="chk" />
              <th>Ticker</th>
              <th className="r">Last</th>
              <th className="r">Chg %</th>
              <th>20 days</th>
              <th className="r">RVOL</th>
              <th>Today</th>
              <th>Note</th>
              <th>Added</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const t = String(r.ticker);
              const h = hits[t];
              const chg = num(r.chg_pct);
              return (
                <tr key={t} className={picked.has(t) ? "picked" : undefined}>
                  <td className="chk">
                    <input type="checkbox" aria-label={`Select ${t}`} checked={picked.has(t)} onChange={() => toggle(t)} />
                  </td>
                  <td>
                    <button className="wl-sym" onClick={() => openChart(t, `wl:${name}`)} title={nameOf(t) || undefined}>
                      {t}
                    </button>
                    {nameOf(t) && <small className="co muted">{nameOf(t)}</small>}
                  </td>
                  <td className="r num">{num(r.close)?.toFixed(2) ?? "–"}</td>
                  <td className={`r num ${dir(chg)}`}>{pct(chg)}</td>
                  <td>
                    <Sparkline closes={sparks[t]} />
                  </td>
                  <td className="r num">{num(r.rvol50)?.toFixed(1) ?? "–"}</td>
                  <td>{h ? <span className="today-hit">{h.grade && <GradeBadge grade={h.grade} />} {h.setup}</span> : <span className="muted">–</span>}</td>
                  <td className="muted">{typeof r.note === "string" ? r.note : ""}</td>
                  <td className="muted">{added(r.added)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {list !== null && rows.length === 0 && <p className="muted wl-main-pad">No stocks in this list yet. Add some above.</p>}
      </div>
      <p className="muted hint wl-main-pad">
        <a href={hrefFor("chart", "", { list: `wl:${name}` })}>Open this list on the Chart</a>
      </p>
    </>
  );
}

/** A 56 px phone row: tap opens the Chart, swipe left removes, long-press starts selecting. */
function SwipeRow({
  children,
  selecting,
  selected,
  onToggle,
  onOpen,
  onRemove,
}: {
  children: React.ReactNode;
  selecting: boolean;
  selected: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onRemove: () => void;
}) {
  const [dx, setDx] = useState(0);
  const start = useRef<{ x: number; y: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressed = useRef(false);
  const clear = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  return (
    <li className={`swipe${selected ? " picked" : ""}`}>
      <button className="swipe-remove" aria-label="Remove from the list" onClick={onRemove}>
        Remove
      </button>
      <div
        className="swipe-row"
        style={{ transform: `translateX(${dx}px)` }}
        onTouchStart={(e) => {
          start.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
          longPressed.current = false;
          timer.current = setTimeout(() => {
            longPressed.current = true;
            onToggle();
          }, 500);
        }}
        onTouchMove={(e) => {
          if (!start.current) return;
          const d = e.touches[0].clientX - start.current.x;
          if (Math.abs(d) > 8) clear();
          setDx(Math.max(-96, Math.min(0, d)));
        }}
        onTouchEnd={() => {
          clear();
          setDx((d) => (d < -48 ? -96 : 0));
          start.current = null;
        }}
        onClick={() => {
          if (dx !== 0) return setDx(0);
          if (longPressed.current) return;
          if (selecting) onToggle();
          else onOpen();
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && (selecting ? onToggle() : onOpen())}
      >
        {selecting && <input type="checkbox" aria-label="Select" checked={selected} readOnly />}
        {children}
      </div>
    </li>
  );
}
