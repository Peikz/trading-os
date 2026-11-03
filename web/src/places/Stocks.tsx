// Stocks: "Find and study a stock" (design review 4 Nov 2026). Left, the sources: MY LISTS (your
// watchlists, price alerts, EP-Watch and BO-Watch), SCREENS (all stocks, your saved screens and
// the examples) and SCAN HITS · LAST CLOSE (each scan of the newest EOD run, or any other run).
// Filters are removable chips with "+ Filter"; the count; Grid (mini candle charts with change,
// daily range, RS and grade) or Table. Clicking a stock opens its full chart (drawing, AVWAPs,
// minute bars, notes) in place, with a scan hit's grading form under it. Watchlist editing and
// saving a screen live here. A screen is a list to look at: no grade, no buy.
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type Filter,
  type RunInfo,
  type ScreenerMeta,
  type ScreenRequest,
  type ScreenResult,
  type ScreenSpec,
  type Spark,
  type Value,
  type WatchList,
} from "../api";
import { GradeBadge } from "../components/Card";
import { MiniCandles } from "../components/MiniCandles";
import { cell, download, formatValue } from "../format";
import { Chart } from "../pages/Chart";
import { describeFilter, FilterRow, flipLink, HitGrading } from "../pages/Screener";
import { AddToList, PriceAlerts, ScanLists } from "../pages/Watchlists";
import { plain } from "../plain";
import { go } from "../routes";
import { Icon } from "../ui/Icon";
import { Segmented, usePopover } from "../ui/kit";
import { GREEN, WatchButton } from "./today/WatchNote";

const BLANK: ScreenSpec = { filters: [], sort: "rs_pct", descending: true };
const NEW_FILTER: Filter = { field: "adr20_pct", op: ">=", value: 4 };
const PAGE = 30;
type View = "grid" | "table";

function readView(): View {
  try {
    return window.localStorage.getItem("trading-os.stocks-view") === "table" ? "table" : "grid";
  } catch {
    return "grid";
  }
}

export function Stocks({ params }: { params: URLSearchParams }) {
  const [meta, setMeta] = useState<ScreenerMeta | null>(null);
  const [lists, setLists] = useState<string[] | null>(null);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [run, setRun] = useState("");
  const [scans, setScans] = useState<{ id: string; label: string; count: number }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tickers, setTickers] = useState<string[]>([]);
  const [signals, setSignals] = useState<Record<string, string>>({});
  const [newList, setNewList] = useState<string | null>(null);

  const loadLists = useCallback(
    () => api.watchlists().then((w) => setLists(w.lists), () => setLists([])),
    [],
  );
  useEffect(() => {
    api.screenerMeta().then(setMeta, (e: Error) => setError(e.message));
    loadLists();
    api.runs().then((r) => {
      setRuns(r);
      const eod = r.find((x) => x.slot === "eod") ?? r[0];
      if (eod) setRun(eod.id);
    }, () => setRuns([]));
  }, [loadLists]);
  useEffect(() => {
    if (!run) return;
    api.runScans(run).then(
      (r) => setScans(Object.entries(r.scans).map(([id, s]) => ({ id, label: s.label, count: s.count }))),
      () => setScans([]),
    );
  }, [run]);

  // The source in the address (?src=list:Name), with "lists" and "scans" meaning the first one
  const raw = params.get("src") ?? "lists";
  const src =
    raw === "lists"
      ? lists === null
        ? null
        : lists.length
          ? `list:${lists[0]}`
          : "all"
      : raw === "scans"
        ? scans.length
          ? `scan:${scans[0].id}`
          : null
        : raw;
  const open = params.get("t")?.toUpperCase() || null;
  const pick = (s: string) => {
    setNewList(null);
    go("stocks", "", { src: s });
  };
  const runLabel = runs.find((r) => r.id === run)?.label ?? "";
  const label = sourceLabel(src, scans);

  return (
    <div>
      <div className="place-head">
        <h1>Stocks</h1>
        <span className="muted">Find and study a stock</span>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="stocks">
        <nav className="sources" aria-label="Sources">
          <div className="section-label">My lists</div>
          <ul>
            {(lists ?? []).map((l) => (
              <Source key={l} id={`list:${l}`} label={l} current={src} onPick={pick} />
            ))}
            <li>
              <button onClick={() => setNewList("")} aria-current={newList !== null}>
                <span className="muted">
                  <Icon name="plus" size={14} />
                </span>
                <span style={{ marginRight: "auto", marginLeft: 8 }}>New list</span>
              </button>
            </li>
            <Source id="alerts" label="Price alerts" current={src} onPick={pick} />
            <Source id="scanlist:ep_watch" label="EP-Watch" current={src} onPick={pick} />
            <Source id="scanlist:bo_watch" label="BO-Watch" current={src} onPick={pick} />
          </ul>
          <div className="section-label">Screens</div>
          <ul>
            <Source id="all" label="All stocks" current={src} onPick={pick} />
            {Object.keys(meta?.saved ?? {}).map((n) => (
              <Source key={n} id={`screen:${n}`} label={n} current={src} onPick={pick} />
            ))}
            {Object.keys(meta?.examples ?? {}).map((n) => (
              <Source key={n} id={`example:${n}`} label={n} hint="example" current={src} onPick={pick} />
            ))}
          </ul>
          <div className="section-label">
            <span>Scan hits · {runs.find((r) => r.id === run)?.slot === "eod" ? "last close" : "run"}</span>
          </div>
          <ul>
            {scans.map((s) => (
              <Source key={s.id} id={`scan:${s.id}`} label={s.label} hint={String(s.count)} current={src} onPick={pick} />
            ))}
            {!scans.length && <li className="queue-note">No scan hits in this run.</li>}
          </ul>
          {runs.length > 1 && (
            <select aria-label="Run" value={run} onChange={(e) => setRun(e.target.value)} style={{ marginTop: 8, width: "100%" }}>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          )}
        </nav>
        <section className="stocks-main" aria-label={label}>
          {newList !== null ? (
            <NewList
              name={newList}
              onName={setNewList}
              onAdded={(name) => {
                loadLists().then(() => pick(`list:${name}`));
              }}
            />
          ) : (
            <>
              {open && (
                <StockDetail
                  ticker={open}
                  tickers={tickers}
                  back={label}
                  onBack={() => go("stocks", "", src ? { src } : {})}
                  onPick={(t) => go("stocks", "", { ...(src ? { src } : {}), t })}
                  signalId={src?.startsWith("scan:") ? signals[open] : undefined}
                  scanLabel={src?.startsWith("scan:") ? label : null}
                />
              )}
              <div hidden={Boolean(open)}>
                {src === "alerts" && <PriceAlerts />}
                {src?.startsWith("scanlist:") && <ScanLists only={src.slice(9)} />}
                {src && meta && isResults(src) && (
                  <Results
                    key={`${src}|${run}`}
                    src={src}
                    meta={meta}
                    run={run}
                    runLabel={runLabel}
                    label={label}
                    onMeta={setMeta}
                    onResult={(r) => {
                      setTickers(r.tickers);
                      setSignals(r.signal_ids);
                    }}
                    onOpen={(t) => go("stocks", "", { src, t })}
                    onListsChanged={loadLists}
                  />
                )}
                {src === null && <p className="muted">Loading…</p>}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

const isResults = (src: string) => /^(list|screen|example|scan):/.test(src) || src === "all";

function sourceLabel(src: string | null, scans: { id: string; label: string }[]): string {
  if (!src) return "Stocks";
  if (src === "all") return "All stocks";
  if (src === "alerts") return "Price alerts";
  if (src === "scanlist:ep_watch") return "EP-Watch";
  if (src === "scanlist:bo_watch") return "BO-Watch";
  const [kind, ...rest] = src.split(":");
  const name = rest.join(":");
  if (kind === "scan") return scans.find((s) => s.id === name)?.label ?? name;
  return name;
}

function Source({
  id,
  label,
  hint,
  current,
  onPick,
}: {
  id: string;
  label: string;
  hint?: string;
  current: string | null;
  onPick: (id: string) => void;
}) {
  return (
    <li>
      <button aria-current={current === id} onClick={() => onPick(id)}>
        <span>{label}</span>
        {hint && <span className="count">{hint}</span>}
      </button>
    </li>
  );
}

function NewList({ name, onName, onAdded }: { name: string; onName: (n: string) => void; onAdded: (n: string) => void }) {
  return (
    <section className="card" aria-label="New list">
      <h3>New list</h3>
      <input aria-label="New list name" placeholder="Name of the list" value={name} onChange={(e) => onName(e.target.value)} />
      <AddToList name={name} onAdded={onAdded} />
      <p className="muted hint">Saved in the data repo; it is pushed to GitHub with your other changes.</p>
    </section>
  );
}

function specOf(src: string, meta: ScreenerMeta): ScreenSpec {
  if (src.startsWith("screen:")) return meta.saved[src.slice(7)] ?? BLANK;
  if (src.startsWith("example:")) return meta.examples[src.slice(8)] ?? BLANK;
  return BLANK;
}

function Results({
  src,
  meta,
  run,
  runLabel,
  label,
  onMeta,
  onResult,
  onOpen,
  onListsChanged,
}: {
  src: string;
  meta: ScreenerMeta;
  run: string;
  runLabel: string;
  label: string;
  onMeta: (m: ScreenerMeta) => void;
  onResult: (r: ScreenResult) => void;
  onOpen: (t: string) => void;
  onListsChanged: () => Promise<unknown>;
}) {
  const kind = src.split(":")[0];
  const name = src.slice(kind.length + 1);
  const [spec, setSpec] = useState<ScreenSpec>(() => specOf(src, meta));
  const [live, setLive] = useState(false);
  const [tiers, setTiers] = useState<string[]>(["alert", "log"]);
  const [result, setResult] = useState<ScreenResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [view, setViewState] = useState<View>(readView);
  const [version, setVersion] = useState(0);
  const [list, setList] = useState<WatchList | null>(null);
  const setView = (v: View) => {
    setViewState(v);
    try {
      window.localStorage.setItem("trading-os.stocks-view", v);
    } catch {
      /* a private window */
    }
  };

  useEffect(() => {
    const body: ScreenRequest = {
      ...spec,
      source: kind === "scan" ? "hits" : kind === "list" ? "list" : "all",
      data: live ? "live" : "close",
      run: kind === "scan" ? run : null,
      scan: kind === "scan" ? name : null,
      watchlist: kind === "list" ? name : null,
      tiers,
    };
    if (kind === "scan" && !run) return;
    let on = true;
    const timer = setTimeout(() => {
      setBusy(true);
      setError(null);
      api
        .runScreen(body)
        .then(
          (r) => {
            if (!on) return;
            setResult(r);
            onResult(r);
          },
          (e: Error) => {
            if (!on) return;
            setError(e.message);
            setResult(null);
          },
        )
        .finally(() => on && setBusy(false));
    }, 250);
    return () => {
      on = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onResult is the parent's setter
  }, [spec, live, tiers, kind, name, run, version]);

  useEffect(() => {
    if (kind !== "list") return;
    api.watchlist(name).then(setList, () => setList(null));
  }, [kind, name, version]);

  const setFilter = (i: number, f: Filter) =>
    setSpec((s) => ({ ...s, filters: s.filters.map((x, k) => (k === i ? f : x)) }));
  const removeFilter = (i: number) => setSpec((s) => ({ ...s, filters: s.filters.filter((_, k) => k !== i) }));
  const fields = Object.keys(meta.fields);
  const empty404 = kind === "list" && error?.startsWith("No stocks");

  const save = (as: string) =>
    api.saveScreen(as, spec).then(
      (saved) => {
        onMeta({ ...meta, saved });
        go("stocks", "", { src: `screen:${as.trim()}` });
      },
      (e: Error) => setError(e.message),
    );
  const remove = () =>
    api.deleteScreen(name).then(
      (saved) => {
        onMeta({ ...meta, saved });
        go("stocks", "", { src: "all" });
      },
      (e: Error) => setError(e.message),
    );
  const removeFromList = (t: string) =>
    api.removeFromWatchlist(name, [t]).then(() => {
      setVersion((v) => v + 1);
      onListsChanged();
    }, (e: Error) => setError(e.message));

  return (
    <div>
      <div className="toolbar">
        <h2>{label}</h2>
        <span className="muted">
          {busy && !result ? "Loading…" : result ? `${result.count} ${result.count === 1 ? "stock" : "stocks"} · ${result.when}` : ""}
        </span>
        <span className="grow" />
        {(kind === "all" || kind === "screen" || kind === "example") && (
          <Segmented
            label="Data"
            options={[["close", "Last close"], ["live", "Live now"]] as const}
            value={live ? "live" : "close"}
            onPick={(v) => setLive(v === "live")}
          />
        )}
        <Segmented
          label="View"
          options={[["grid", <><Icon name="grid" size={16} /> Grid</>], ["table", <><Icon name="table" size={16} /> Table</>]] as const}
          value={view}
          onPick={setView}
        />
      </div>
      {kind === "scan" && (
        <p className="muted hint">
          {label} hits, {runLabel}. Sorted best study grade first, as in the push. Scan hits keep their study grade.
        </p>
      )}
      {kind !== "scan" && kind !== "list" && (
        <p className="muted hint">A screen of all stocks is a list to look at, not a tested setup: no grade, no buy.</p>
      )}
      <div className="chips" aria-label="Filters">
        {spec.filters.map((f, i) => (
          <FilterChip
            key={i}
            text={describeFilter(meta, f)}
            onRemove={() => removeFilter(i)}
            editor={<FilterRow meta={meta} fields={fields} filter={f} onChange={(nf) => setFilter(i, nf)} onRemove={() => removeFilter(i)} />}
          />
        ))}
        <button
          className="add-filter"
          onClick={() => setSpec((s) => ({ ...s, filters: [...s.filters, NEW_FILTER] }))}
        >
          <Icon name="plus" size={14} />
          Filter
        </button>
        {kind === "scan" &&
          ["alert", "log"].map((t) => (
            <label key={t} className="check">
              <input
                type="checkbox"
                checked={tiers.includes(t)}
                onChange={() => setTiers((x) => (x.includes(t) ? x.filter((y) => y !== t) : [...x, t]))}
              />
              {t === "alert" ? "Alert tier" : "Log tier"}
            </label>
          ))}
        {kind !== "scan" && (
          <>
            <label className="muted">
              Sort by{" "}
              <select aria-label="Sort by" value={spec.sort ?? "rs_pct"} onChange={(e) => setSpec({ ...spec, sort: e.target.value })}>
                {fields.map((f) => (
                  <option key={f} value={f}>
                    {plain(meta.fields[f].label).text}
                  </option>
                ))}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={spec.descending} onChange={(e) => setSpec({ ...spec, descending: e.target.checked })} />
              Highest first
            </label>
          </>
        )}
      </div>
      {kind === "list" && <AddToList name={name} onAdded={() => { setVersion((v) => v + 1); onListsChanged(); }} />}
      {error && !empty404 && <p className="error">{error}</p>}
      {empty404 && <p className="muted">No stocks in this list yet. Add some above.</p>}
      {result && result.count === 0 && <p className="muted">No stocks match these filters.</p>}
      {result && result.count > 0 && (
        <>
          {view === "grid" ? (
            <Grid result={result} meta={meta} onOpen={onOpen} onRemove={kind === "list" ? removeFromList : undefined} />
          ) : kind === "list" && list ? (
            <ListTable list={list} keep={result.tickers} onOpen={onOpen} onRemove={removeFromList} />
          ) : (
            <ResultTable result={result} meta={meta} onOpen={onOpen} />
          )}
          {result.rows.length < result.count && <p className="muted">The first {result.rows.length} shown.</p>}
        </>
      )}
      {result && (
        <div className="row">
          {kind !== "list" && result.tickers.length > 0 && (
            <button onClick={() => (window.location.href = flipLink(kind === "screen" ? name : label, result.tickers))}>
              Flip through on Today ({result.tickers.length})
            </button>
          )}
          <button
            title="TradingView: Watchlist menu, Import list"
            disabled={!result.tickers.length}
            onClick={() => download(kind === "scan" ? `${run}_${name}.txt` : `${label}.txt`, kind === "list" && list ? list.tv_list : result.tv_list)}
          >
            TradingView list (.txt)
          </button>
          {kind !== "scan" && kind !== "list" && <SaveScreen initial={kind === "screen" ? name : ""} onSave={save} />}
          {kind === "screen" && (
            <button className="ghost" onClick={remove}>
              Delete '{name}'
            </button>
          )}
        </div>
      )}
      {kind === "list" && list?.label && (
        <p className="muted hint">Market data from {list.label}. In scans: the scans it hit that run.</p>
      )}
    </div>
  );
}

function FilterChip({ text, editor, onRemove }: { text: string; editor: React.ReactNode; onRemove: () => void }) {
  const { open, setOpen, ref } = usePopover<HTMLSpanElement>();
  return (
    <span className="chip popover-wrap" ref={ref}>
      <button className="edit" aria-expanded={open} onClick={() => setOpen(!open)} title="Edit this filter">
        {text}
      </button>
      <button aria-label={`Remove filter: ${text}`} onClick={onRemove}>
        <Icon name="x" size={14} />
      </button>
      {open && (
        <div className="popover left filter-form" role="dialog" aria-label="Edit filter" style={{ width: 520 }}>
          {editor}
          <div className="row">
            <button className="primary" onClick={() => setOpen(false)}>
              Done
            </button>
          </div>
        </div>
      )}
    </span>
  );
}

function SaveScreen({ initial, onSave }: { initial: string; onSave: (name: string) => void }) {
  const { open, setOpen, ref } = usePopover();
  const [name, setName] = useState(initial);
  return (
    <div className="popover-wrap" ref={ref}>
      <button onClick={() => setOpen(!open)} aria-expanded={open}>
        Save screen
      </button>
      {open && (
        <div className="popover left" role="dialog" aria-label="Save screen">
          <input aria-label="Screen name" placeholder="Name to save as" value={name} onChange={(e) => setName(e.target.value)} />
          <div className="row">
            <button
              className="primary"
              disabled={!name.trim()}
              onClick={() => {
                onSave(name);
                setOpen(false);
              }}
            >
              Save
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const num = (r: Record<string, Value>, k: string) => (typeof r[k] === "number" ? (r[k] as number) : null);

function Grid({
  result,
  meta,
  onOpen,
  onRemove,
}: {
  result: ScreenResult;
  meta: ScreenerMeta;
  onOpen: (t: string) => void;
  onRemove?: (t: string) => void;
}) {
  const [shown, setShown] = useState(PAGE);
  const rows = result.rows.slice(0, shown);
  const key = rows.map((r) => r.ticker).join(",");
  const [sparks, setSparks] = useState<Record<string, Spark>>({});
  useEffect(() => {
    const want = key.split(",").filter((t) => t && !(t in sparks));
    if (!want.length) return;
    let live = true;
    for (let i = 0; i < want.length; i += 30) {
      api.sparks(want.slice(i, i + 30), 60).then((s) => live && setSparks((x) => ({ ...x, ...s })), () => {});
    }
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only new tickers are fetched
  }, [key]);
  return (
    <>
      <div className="grid3" aria-label="Grid">
        {rows.map((r) => {
          const t = String(r.ticker);
          const chg = num(r, "chg_pct");
          const adr = num(r, "adr20_pct");
          const rs = num(r, "rs_pct");
          return (
            <div key={t} style={{ position: "relative" }}>
              <button className="tile-card" onClick={() => onOpen(t)} aria-label={`Open ${t}`}>
                <div className="top-line">
                  {typeof r.grade === "string" && r.grade && <GradeBadge grade={r.grade} />}
                  <span className="tk">{t}</span>
                  {chg !== null && (
                    <span className={`chg num ${chg >= 0 ? "up" : "down"}`}>{formatValue(chg, "pct")}</span>
                  )}
                </div>
                <div className="facts">
                  <span title="ADR %: average daily range over 20 days">Range {adr === null ? "–" : `${adr.toFixed(1)}%`}</span>
                  <span title={plain("rs_pct").title}>RS {rs === null ? "–" : rs.toFixed(0)}</span>
                  {typeof r.close === "number" && <span>{formatValue(r.close, meta.fields.close?.kind ?? "money")}</span>}
                </div>
                {sparks[t] ? <MiniCandles candles={sparks[t]} label={t} /> : <svg className="mini" aria-hidden="true" />}
              </button>
              {onRemove && (
                <button
                  className="ghost icon-btn"
                  style={{ position: "absolute", top: 6, right: 6 }}
                  aria-label={`Remove ${t} from the list`}
                  onClick={() => onRemove(t)}
                >
                  <Icon name="x" size={14} />
                </button>
              )}
            </div>
          );
        })}
      </div>
      {result.rows.length > shown && (
        <div className="row">
          <button onClick={() => setShown((s) => s + PAGE)}>Show {Math.min(PAGE, result.rows.length - shown)} more</button>
        </div>
      )}
    </>
  );
}

function Head({ column, meta }: { column: string; meta?: ScreenerMeta }) {
  const label = column === "grade" ? "Grade" : (meta?.fields[column]?.label ?? column);
  const p = plain(label);
  return <th title={p.title}>{p.text}</th>;
}

function ResultTable({ result, meta, onOpen }: { result: ScreenResult; meta: ScreenerMeta; onOpen: (t: string) => void }) {
  return (
    <div className="table-wrap">
      <table aria-label="Results">
        <thead>
          <tr>
            {result.columns.map((c) => (
              <Head key={c} column={c} meta={meta} />
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((r, i) => (
            <tr key={`${r.ticker}-${i}`} className="clickable" onClick={() => onOpen(String(r.ticker))}>
              {result.columns.map((c) => (
                <td key={c}>
                  {c === "grade" && typeof r[c] === "string" ? (
                    <GradeBadge grade={r[c] as string} />
                  ) : c === "ticker" ? (
                    <b>{r[c] as string}</b>
                  ) : (
                    formatValue(r[c] as Value, meta.fields[c]?.kind)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ListTable({
  list,
  keep,
  onOpen,
  onRemove,
}: {
  list: WatchList;
  keep: string[];
  onOpen: (t: string) => void;
  onRemove: (t: string) => void;
}) {
  const shown = useMemo(() => {
    const set = new Set(keep);
    return list.rows.filter((r) => set.has(String(r.ticker)));
  }, [list, keep]);
  const columns = list.columns.filter((c) => c !== "exchange");
  return (
    <div className="table-wrap">
      <table aria-label={`Watchlist ${list.name}`}>
        <thead>
          <tr>
            {columns.map((c) => (
              <Head key={c} column={c} />
            ))}
            <th aria-label="Remove" />
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={String(r.ticker)} className="clickable" onClick={() => onOpen(String(r.ticker))}>
              {columns.map((c) => (
                <td key={c}>{c === "ticker" ? <b>{String(r.ticker)}</b> : cell(c, r[c] as Value)}</td>
              ))}
              <td>
                <button
                  className="ghost icon-btn"
                  aria-label={`Remove ${r.ticker} from the list`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemove(String(r.ticker));
                  }}
                >
                  <Icon name="x" size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StockDetail({
  ticker,
  tickers,
  back,
  onBack,
  onPick,
  signalId,
  scanLabel,
}: {
  ticker: string;
  tickers: string[];
  back: string;
  onBack: () => void;
  onPick: (t: string) => void;
  signalId: string | undefined;
  scanLabel: string | null;
}) {
  const [watching, setWatching] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const load = useCallback(
    () =>
      api.watchlist(GREEN).then(
        (l) => setWatching(l.rows.some((r) => String(r.ticker) === ticker)),
        () => setWatching(false),
      ),
    [ticker],
  );
  useEffect(() => {
    load();
    setMessage(null);
  }, [load]);
  const k = tickers.indexOf(ticker);
  const toggle = () =>
    (watching ? api.removeFromWatchlist(GREEN, [ticker]) : api.flag(ticker, GREEN)).then(
      () => {
        setMessage(watching ? `${ticker} is off your watchlist` : `${ticker} is on your watchlist`);
        load();
      },
      (e: Error) => setMessage(`Error: ${e.message}`),
    );
  return (
    <section aria-label={`${ticker} full chart`}>
      <div className="detail-head">
        <button className="ghost" onClick={onBack}>
          <Icon name="back" size={16} />
          {back}
        </button>
        <span className="grow" style={{ flex: 1 }} />
        {k >= 0 && tickers.length > 1 && (
          <>
            <button className="icon-btn" aria-label="Previous stock" onClick={() => onPick(tickers[(k - 1 + tickers.length) % tickers.length])}>
              <Icon name="left" />
            </button>
            <span className="muted num">
              {k + 1} of {tickers.length}
            </span>
            <button className="icon-btn" aria-label="Next stock" onClick={() => onPick(tickers[(k + 1) % tickers.length])}>
              <Icon name="right" />
            </button>
          </>
        )}
      </div>
      <div className="chart-head">
        <span className="ticker">{ticker}</span>
        <WatchButton watching={watching} onToggle={toggle} />
        {message && <span className={message.startsWith("Error") ? "error" : "muted"}>{message}</span>}
      </div>
      <Chart ticker={ticker} />
      {scanLabel && <HitGrading ticker={ticker} signalId={signalId} scanLabel={scanLabel} />}
    </section>
  );
}
