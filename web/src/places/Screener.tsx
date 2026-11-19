// The Screener (UX round 3, 18 Nov 2026, the owner's approved mockup): a place of its own with two
// pages. "Scan hits": the hits of one run of today or all of them (the same run picker as Today),
// one scan or all, by grade. "Screener": every stock in the last close, narrowed by a saved or
// example screen and your own filter chips. Everything is chosen in one filter bar at the top; the
// table gets the rest of the page, with column views (Overview / Technical / Setup), a preview
// panel for the selected row (desktop) and a Table / Charts toggle. A screen is a list to look at:
// no grade, no buy. Saved screens stay where Streamlit keeps them (`/api/screens`).
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type Filter,
  type ScanHits,
  type ScreenerMeta,
  type ScreenResult,
  type ScreenSpec,
  type Spark,
} from "../api";
import { GradeBadge } from "../components/Card";
import { MiniCandles } from "../components/MiniCandles";
import { download, formatValue } from "../format";
import { describeFilter, FilterRow } from "../pages/Screener";
import { openChart } from "../shell/active";
import { useArrowKeys, usePref } from "../shell/prefs";
import { nameOf, useNames } from "../shell/symbols";
import { useRunPick, useTodayRuns } from "../shell/todayRun";
import { Icon } from "../ui/Icon";
import { PHONE, typing, useMedia, usePopover } from "../ui/kit";
import { RunMenu } from "../ui/RunPicker";
import { useVisibleSparks } from "./chart/lists";
import { onePerStock } from "./screener/oneRow";
import { Sparkline } from "./chart/WatchPanel";
import { Preview, type Rec } from "./screener/Preview";

type Page = "hits" | "screen";
type ViewName = "Overview" | "Technical" | "Setup";
type Kind = "text" | "grade" | "money" | "pct" | "pp" | "num" | "x" | "r" | "win" | "bool" | "spark" | "runs";
interface Col {
  key: string;
  label: string;
  kind: Kind;
  title?: string;
}

const T: Col = { key: "ticker", label: "Ticker", kind: "text" };
const G: Col = { key: "grade", label: "Grade", kind: "grade" };
const LAST: Col = { key: "close", label: "Last", kind: "money" };
const CHG: Col = { key: "chg_pct", label: "Chg %", kind: "pct" };
const SPARK: Col = { key: "spark", label: "20 days", kind: "spark" };

const HIT_VIEWS: Record<ViewName, Col[]> = {
  Overview: [T, G, { key: "scan_label", label: "Setup", kind: "text" }, LAST, CHG, SPARK, { key: "rvol50", label: "RVOL", kind: "num", title: "Volume against its 50-day average" }, { key: "adr20_pct", label: "ADR %", kind: "pp", title: "Average daily range, 20 days" }, { key: "runs", label: "Runs", kind: "runs" }],
  Technical: [T, G, { key: "rs_pct", label: "RS", kind: "num", title: "Relative strength percentile (1-99)" }, { key: "pct_from_52w_high", label: "From high", kind: "pct", title: "From the 52-week high" }, { key: "ret_22", label: "1 month", kind: "pct" }, { key: "ret_63", label: "3 months", kind: "pct" }, { key: "dist_ma10_adr", label: "To 10-day line", kind: "num", title: "Distance to the 10-day line, in ADRs" }, { key: "above_ma50", label: "Over 50-day", kind: "bool" }, { key: "above_ma200", label: "Over 200-day", kind: "bool" }],
  Setup: [T, G, { key: "scan_label", label: "Setup", kind: "text" }, { key: "grade_stat_mean_r", label: "Pred. R", kind: "r", title: "The study's average R for this grade" }, { key: "grade_stat_win_pct", label: "Win %", kind: "win" }, { key: "grade_why", label: "Why", kind: "text" }, { key: "si_tag", label: "Short", kind: "text" }, { key: "ibd_tag", label: "IBD", kind: "text" }, { key: "vol_build", label: "Vol build", kind: "x" }],
};
const SCREEN_VIEWS: Record<ViewName, Col[]> = {
  Overview: [T, LAST, CHG, SPARK, { key: "rvol50", label: "RVOL", kind: "num" }, { key: "adr20_pct", label: "ADR %", kind: "pp" }, { key: "market_cap", label: "Market cap", kind: "money" }, { key: "industry", label: "Industry", kind: "text" }],
  Technical: [T, { key: "rs_pct", label: "RS", kind: "num" }, { key: "pct_from_52w_high", label: "From high", kind: "pct" }, { key: "ret_22", label: "1 month", kind: "pct" }, { key: "ret_63", label: "3 months", kind: "pct" }, { key: "dist_ma10_adr", label: "To 10-day line", kind: "num" }, { key: "above_ma50", label: "Over 50-day", kind: "bool" }, { key: "above_ma200", label: "Over 200-day", kind: "bool" }],
  Setup: [T, { key: "vol_build", label: "Vol build", kind: "x" }, { key: "hist_range_nd", label: "10-day range", kind: "num", title: "10-day range in ADRs (tightness)" }, { key: "earnings_in_sessions", label: "Earnings in", kind: "num", title: "Sessions to the next report" }, { key: "industry_rank", label: "Industry rank", kind: "num" }, { key: "minervini_tt", label: "Trend template", kind: "bool" }, { key: "ma_surf", label: "MA-surf", kind: "bool" }],
};
const VIEWS: ViewName[] = ["Overview", "Technical", "Setup"];
const GRADE_RANK: Record<string, number> = { "A+++": 0, "A++": 1, "A+": 2, A: 3, B: 4, C: 5, "": 9 };
const GRADES = ["All", "A+", "A", "B", "C"] as const;
const BLANK: ScreenSpec = { filters: [], sort: "rs_pct", descending: true };
const NEW_FILTER: Filter = { field: "adr20_pct", op: ">=", value: 4 };

const num = (v: unknown): number | null => (typeof v === "number" && !Number.isNaN(v) ? v : null);

function show(kind: Kind, v: unknown): string {
  if (v === null || v === undefined || v === "") return "–";
  if (kind === "bool") return v ? "yes" : "no";
  if (typeof v !== "number") return String(v);
  switch (kind) {
    case "money":
      return formatValue(v, "money");
    case "pct":
      return formatValue(v, "pct");
    case "pp":
      return `${v.toFixed(1)}%`;
    case "x":
      return `${v.toFixed(1)}x`;
    case "r":
      return `${v >= 0 ? "+" : ""}${v.toFixed(2)}R`;
    case "win":
      return `${v.toFixed(0)}%`;
    case "num":
      return Number.isInteger(v) ? String(v) : v.toFixed(1);
    default:
      return String(v);
  }
}
const NUMERIC: Kind[] = ["money", "pct", "pp", "num", "x", "r", "win"];

function gradeFilter(g: (typeof GRADES)[number], rec: Rec): boolean {
  const grade = String(rec.grade ?? "");
  if (g === "All") return true;
  if (g === "A+") return grade.startsWith("A+");
  return grade === g;
}

function csv(cols: Col[], rows: Rec[]): string {
  const q = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const real = cols.filter((c) => c.kind !== "spark");
  return [real.map((c) => q(c.label)).join(","), ...rows.map((r) => real.map((c) => q(c.key === "runs" ? (r.runs as string[] | undefined)?.join(" ") : r[c.key])).join(","))].join("\n");
}

export function Screener({ tab, params }: { tab: string; params: URLSearchParams }) {
  const page: Page = tab === "screen" ? "screen" : "hits";
  const phone = useMedia(PHONE);
  const [view, setView] = usePref<ViewName>("screener-view", "Overview");
  const [mode, setMode] = usePref<"table" | "charts">("screener-mode", "table");
  const [arrowKeys] = useArrowKeys();
  useNames();

  // The page's data, as plain records
  const [rows, setRows] = useState<Rec[] | null>(null);
  const [count, setCount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [bar, setBar] = useState<React.ReactNode>(null);
  const [tvList, setTvList] = useState("");
  const [sort, setSort] = useState<{ key: string; down: boolean } | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    setSort(null);
    setSel(null);
  }, [page]);

  const cols = (page === "hits" ? HIT_VIEWS : SCREEN_VIEWS)[view];
  const sorted = useMemo(() => {
    if (!rows || !sort) return rows;
    const kind = cols.find((c) => c.key === sort.key)?.kind;
    const val = (r: Rec): number | string | null => {
      const v = r[sort.key];
      if (kind === "grade") return GRADE_RANK[String(v ?? "")] ?? 8;
      if (v === null || v === undefined || v === "") return null;
      return typeof v === "boolean" ? Number(v) : (v as number | string);
    };
    return [...rows].sort((a, b) => {
      const x = val(a);
      const y = val(b);
      if (x === null && y === null) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      const c = typeof x === "string" ? x.localeCompare(String(y)) : (x as number) - (y as number);
      return sort.down ? -c : c;
    });
  }, [rows, sort, cols]);
  const key = (r: Rec) => `${r.ticker}|${r.scan ?? ""}`;
  const current = sorted?.find((r) => key(r) === sel) ?? (phone ? null : sorted?.[0] ?? null);
  const open = (r: Rec) => openChart(String(r.ticker), page === "hits" && ["A+++", "A++", "A+", "A", "B"].includes(String(r.grade)) ? "hits" : undefined);

  useEffect(() => {
    if (!arrowKeys || !sorted?.length) return;
    const onKey = (e: KeyboardEvent) => {
      if (typing(e) || e.ctrlKey || e.metaKey || e.altKey || document.querySelector(".palette-back")) return;
      const at = current ? sorted.findIndex((r) => key(r) === key(current)) : -1;
      if (e.key === "ArrowDown" || e.key.toLowerCase() === "j") setSel(key(sorted[Math.min(sorted.length - 1, at + 1)]));
      else if (e.key === "ArrowUp" || e.key.toLowerCase() === "k") setSel(key(sorted[Math.max(0, at - 1)]));
      else if (e.key === "Enter" && current) open(current);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `open` only reads `page`
  }, [sorted, current, arrowKeys, page]);

  const filterBar = (
    <div className="filter-bar" role="toolbar" aria-label="Filters">
      <div className="fb-left">{bar}</div>
      <span className="grow" />
      <span className="muted fb-count" aria-live="polite">{error ? "" : rows === null ? "Loading…" : count}</span>
      <div className="seg-line" role="group" aria-label="View">
        <button aria-pressed={mode === "table"} onClick={() => setMode("table")}>Table</button>
        <button aria-pressed={mode === "charts"} onClick={() => setMode("charts")}>Charts</button>
      </div>
      <ExportMenu
        tv={tvList}
        onCsv={() => download(`${page === "hits" ? "scan-hits" : "screen"}.csv`, csv(cols, sorted ?? []))}
        name={page === "hits" ? "scan-hits" : "screen"}
        disabled={!rows?.length}
      />
    </div>
  );

  const body = (
    <div className="sc-body">
      <section className="sc-main" aria-label="Results">
        <div className="view-tabs" role="tablist" aria-label="Columns">
          {VIEWS.map((v) => (
            <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}>
              {v}
            </button>
          ))}
        </div>
        {error && <p className="error sc-pad">{error}</p>}
        {rows !== null && rows.length === 0 && !error && (
          <p className="muted sc-pad">{page === "hits" ? "No scan hits match these filters." : "No stocks match these filters."}</p>
        )}
        {sorted && sorted.length > 0 && mode === "charts" && <Charts rows={sorted} onOpen={open} />}
        {sorted && sorted.length > 0 && mode === "table" && !phone && (
          <DataTable cols={cols} rows={sorted} sort={sort} onSort={(k) => setSort((s) => (s?.key !== k ? { key: k, down: true } : s.down ? { key: k, down: false } : null))} current={current ? key(current) : null} keyOf={key} onSelect={(r) => setSel(key(r))} onOpen={open} />
        )}
        {sorted && sorted.length > 0 && mode === "table" && phone && <PhoneRows rows={sorted} onOpen={open} page={page} />}
      </section>
      {!phone && mode === "table" && <Preview rec={current} source={page === "hits" ? "A scan hit." : "A screen is a list to look at: no grade, no buy."} onOpen={() => current && open(current)} />}
    </div>
  );

  const common = { setRows, setCount, setError, setBar, setTvList, view };
  return (
    <div className="sc-place">
      {page === "hits" ? <HitsData {...common} key="hits" /> : <ScreenData {...common} params={params} key="screen" />}
      {filterBar}
      {body}
    </div>
  );
}

type Common = {
  setRows: (r: Rec[] | null) => void;
  setCount: (s: string) => void;
  setError: (s: string | null) => void;
  setBar: (n: React.ReactNode) => void;
  setTvList: (s: string) => void;
  view: ViewName;
};

/** Scan hits: Run, Scan and Grade choose the rows; the filter bar shows the three. */
function HitsData({ setRows, setCount, setError, setBar, setTvList }: Common) {
  const runs = useTodayRuns();
  const [run, setRun] = useRunPick();
  const [scan, setScan] = useState("all");
  const [grade, setGrade] = useState<(typeof GRADES)[number]>("All");
  const [data, setData] = useState<ScanHits | null>(null);
  useEffect(() => {
    let live = true;
    setData(null);
    setRows(null);
    api.scanHits(run).then(
      (d) => {
        if (!live) return;
        setData(d);
        setError(null);
      },
      (e: Error) => live && (setError(e.message), setRows([])),
    );
    return () => {
      live = false;
    };
  }, [run, setRows, setError]);
  const picked = useMemo(() => {
    // One row per stock under "All scans" (best grade first, setups joined, runs listed)
    const rows = scan === "all" ? onePerStock(data?.rows ?? []) : (data?.rows ?? []).filter((r) => r.scan === scan);
    return rows.filter((r) => gradeFilter(grade, r as Rec));
  }, [data, scan, grade]);
  useEffect(() => {
    if (!data) return;
    setRows(picked as Rec[]);
    setCount(`${picked.length} ${picked.length === 1 ? "hit" : "hits"}`);
    setTvList([...new Set(picked.map((r) => (r.exchange ? `${r.exchange}:${r.ticker}` : String(r.ticker))))].join(","));
  }, [picked, data, setRows, setCount, setTvList]);
  useEffect(() => {
    setBar(
      <>
        <RunMenu runs={runs} value={run} onPick={setRun} />
        <ScanMenu scans={data?.scans ?? []} value={scan} onPick={setScan} />
        <div className="seg-line" role="group" aria-label="Grade">
          {GRADES.map((g) => (
            <button key={g} aria-pressed={grade === g} onClick={() => setGrade(g)}>
              {g}
            </button>
          ))}
        </div>
      </>,
    );
  }, [runs, run, setRun, data, scan, grade, setBar]);
  return null;
}

function ScanMenu({ scans, value, onPick }: { scans: { id: string; label: string; count: number }[]; value: string; onPick: (id: string) => void }) {
  const { open, setOpen, ref } = usePopover();
  const label = value === "all" ? "All scans" : (scans.find((s) => s.id === value)?.label ?? value);
  const choose = (id: string) => {
    onPick(id);
    setOpen(false);
  };
  return (
    <div className="popover-wrap" ref={ref}>
      <button className="fbtn" aria-expanded={open} aria-haspopup="listbox" onClick={() => setOpen(!open)}>
        <span className="flabel">Scan</span>
        {label}
        <Icon name="down" size={14} />
      </button>
      {open && (
        <div className="popover left menu" role="listbox" aria-label="Scan">
          <button role="option" aria-selected={value === "all"} onClick={() => choose("all")}>
            <span>All scans</span>
          </button>
          {scans.map((s) => (
            <button key={s.id} role="option" aria-selected={value === s.id} onClick={() => choose(s.id)}>
              <span>{s.label}</span>
              <span className="muted num">{s.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Screener: a saved or example screen, your filter chips, Last close / Live now. */
function ScreenData({ setRows, setCount, setError, setBar, setTvList, view, params }: Common & { params: URLSearchParams }) {
  const [meta, setMeta] = useState<ScreenerMeta | null>(null);
  const sector = params.get("sector");
  const [name, setName] = useState<string>("");
  const [spec, setSpec] = useState<ScreenSpec>(() =>
    sector ? { ...BLANK, filters: [{ field: "sector", op: "is one of", value: sector.split(",") }] } : BLANK,
  );
  const [live, setLive] = useState(false);
  const [result, setResult] = useState<ScreenResult | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    api.screenerMeta().then(setMeta, (e: Error) => setError(e.message));
  }, [setError]);
  // Another sector from the Market page
  useEffect(() => {
    if (sector) {
      setName("");
      setSpec({ ...BLANK, filters: [{ field: "sector", op: "is one of", value: sector.split(",") }] });
    }
  }, [sector]);
  const more = useMemo(() => SCREEN_VIEWS[view].map((c) => c.key).filter((k) => !["ticker", "spark"].includes(k)), [view]);
  useEffect(() => {
    let on = true;
    const timer = setTimeout(() => {
      setRows(null);
      api
        .runScreen({ ...spec, source: "all", data: live ? "live" : "close", more })
        .then(
          (r) => {
            if (!on) return;
            setResult(r);
            setRows(r.rows as Rec[]);
            setError(null);
            setCount(`${r.count} ${r.count === 1 ? "stock" : "stocks"} · ${r.when}`);
            setTvList(r.tv_list);
          },
          (e: Error) => {
            if (!on) return;
            setError(e.message);
            setRows([]);
          },
        );
    }, 250);
    return () => {
      on = false;
      clearTimeout(timer);
    };
  }, [spec, live, more, version, setRows, setError, setCount, setTvList]);

  useEffect(() => {
    if (!meta) return;
    const fields = Object.keys(meta.fields);
    const pickScreen = (n: string, s: ScreenSpec) => {
      setName(n);
      setSpec(s);
    };
    setBar(
      <>
        <ScreenMenu
          meta={meta}
          name={name}
          spec={spec}
          onPick={pickScreen}
          onMeta={(saved, as) => {
            setMeta({ ...meta, saved });
            if (as) setName(as);
          }}
          onError={setError}
        />
        {spec.filters.map((f, i) => (
          <FilterChip
            key={i}
            text={describeFilter(meta, f)}
            editor={
              <FilterRow
                meta={meta}
                fields={fields}
                filter={f}
                onChange={(nf) => setSpec((s) => ({ ...s, filters: s.filters.map((x, k) => (k === i ? nf : x)) }))}
                onRemove={() => setSpec((s) => ({ ...s, filters: s.filters.filter((_, k) => k !== i) }))}
              />
            }
            onRemove={() => setSpec((s) => ({ ...s, filters: s.filters.filter((_, k) => k !== i) }))}
          />
        ))}
        <AddFilter meta={meta} fields={fields} onAdd={(f) => setSpec((s) => ({ ...s, filters: [...s.filters, f] }))} />
        <div className="seg-line" role="group" aria-label="Data">
          <button aria-pressed={!live} onClick={() => setLive(false)}>Last close</button>
          <button aria-pressed={live} onClick={() => setLive(true)}>Live now</button>
        </div>
      </>,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rebuilt when its inputs change
  }, [meta, name, spec, live, setBar]);
  void result;
  void version;
  void setVersion;
  return null;
}

function FilterChip({ text, editor, onRemove }: { text: string; editor: React.ReactNode; onRemove: () => void }) {
  const { open, setOpen, ref } = usePopover<HTMLSpanElement>();
  return (
    <span className="fchip popover-wrap" ref={ref}>
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

function AddFilter({ meta, fields, onAdd }: { meta: ScreenerMeta; fields: string[]; onAdd: (f: Filter) => void }) {
  const { open, setOpen, ref } = usePopover();
  const [draft, setDraft] = useState<Filter>(NEW_FILTER);
  return (
    <div className="popover-wrap" ref={ref}>
      <button className="fbtn dashed" aria-expanded={open} onClick={() => setOpen(!open)}>
        + Filter
      </button>
      {open && (
        <div className="popover left filter-form" role="dialog" aria-label="Add a filter" style={{ width: 520 }}>
          <FilterRow meta={meta} fields={fields} filter={draft} onChange={setDraft} onRemove={() => setDraft(NEW_FILTER)} />
          <div className="row">
            <button
              className="primary"
              onClick={() => {
                onAdd(draft);
                setDraft(NEW_FILTER);
                setOpen(false);
              }}
            >
              Add filter
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Screen ▾: all stocks, your saved screens, the examples; save and delete are in the menu. */
function ScreenMenu({
  meta,
  name,
  spec,
  onPick,
  onMeta,
  onError,
}: {
  meta: ScreenerMeta;
  name: string;
  spec: ScreenSpec;
  onPick: (name: string, spec: ScreenSpec) => void;
  onMeta: (saved: ScreenerMeta["saved"], as?: string) => void;
  onError: (e: string | null) => void;
}) {
  const { open, setOpen, ref } = usePopover();
  const [as, setAs] = useState("");
  const choose = (n: string, s: ScreenSpec) => {
    onPick(n, s);
    setOpen(false);
  };
  const save = () =>
    api.saveScreen(as, spec).then(
      (saved) => {
        onMeta(saved, as.trim());
        setAs("");
        setOpen(false);
      },
      (e: Error) => onError(e.message),
    );
  const remove = (n: string) =>
    api.deleteScreen(n).then(
      (saved) => {
        onMeta(saved);
        if (name === n) onPick("", BLANK);
      },
      (e: Error) => onError(e.message),
    );
  return (
    <div className="popover-wrap" ref={ref}>
      <button className="fbtn" aria-expanded={open} aria-haspopup="listbox" onClick={() => setOpen(!open)}>
        <span className="flabel">Screen</span>
        {name || "All stocks"}
        <Icon name="down" size={14} />
      </button>
      {open && (
        <div className="popover left menu wide" role="listbox" aria-label="Screen">
          <button role="option" aria-selected={!name} onClick={() => choose("", BLANK)}>
            <span>All stocks</span>
          </button>
          {Object.keys(meta.saved).length > 0 && <div className="menu-label">Saved</div>}
          {Object.entries(meta.saved).map(([n, s]) => (
            <div className="menu-row" key={n}>
              <button role="option" aria-selected={name === n} onClick={() => choose(n, s)}>
                <span>{n}</span>
              </button>
              <button className="ghost icon-btn" aria-label={`Delete screen ${n}`} onClick={() => remove(n)}>
                <Icon name="x" size={14} />
              </button>
            </div>
          ))}
          <div className="menu-label">Examples</div>
          {Object.entries(meta.examples).map(([n, s]) => (
            <button key={n} role="option" aria-selected={name === n} onClick={() => choose(n, s)}>
              <span>{n}</span>
            </button>
          ))}
          <div className="menu-label">Save this screen</div>
          <div className="menu-save">
            <input aria-label="Screen name" placeholder="Name to save as" value={as} onChange={(e) => setAs(e.target.value)} />
            <button className="primary" disabled={!as.trim()} onClick={save}>
              Save
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ExportMenu({ tv, onCsv, name, disabled }: { tv: string; onCsv: () => void; name: string; disabled: boolean }) {
  const { open, setOpen, ref } = usePopover();
  return (
    <div className="popover-wrap" ref={ref}>
      <button className="fbtn" aria-expanded={open} disabled={disabled} onClick={() => setOpen(!open)}>
        Export
        <Icon name="down" size={14} />
      </button>
      {open && (
        <div className="popover menu" role="menu" aria-label="Export">
          <button role="menuitem" title="TradingView: Watchlist menu, Import list" onClick={() => { download(`${name}.txt`, tv); setOpen(false); }}>
            TradingView list (.txt)
          </button>
          <button role="menuitem" onClick={() => { onCsv(); setOpen(false); }}>
            CSV
          </button>
        </div>
      )}
    </div>
  );
}

function Cell({ col, rec, sparks }: { col: Col; rec: Rec; sparks: Record<string, number[]> }) {
  const v = rec[col.key];
  if (col.kind === "grade") return typeof v === "string" && v ? <GradeBadge grade={v} /> : <span className="muted">–</span>;
  if (col.kind === "spark") return <Sparkline closes={sparks[String(rec.ticker)]} />;
  if (col.kind === "runs") return <span className="muted">{((v as string[] | undefined) ?? []).join(" · ")}</span>;
  if (col.key === "ticker") {
    const name = nameOf(String(v));
    return (
      <>
        <b>{String(v)}</b>
        {name && <small className="co muted">{name}</small>}
      </>
    );
  }
  const n = num(v);
  const cls = col.kind === "pct" && n !== null ? (n >= 0 ? "up" : "down") : "";
  return <span className={cls}>{show(col.kind, v)}</span>;
}

function DataTable({
  cols,
  rows,
  sort,
  onSort,
  current,
  keyOf,
  onSelect,
  onOpen,
}: {
  cols: Col[];
  rows: Rec[];
  sort: { key: string; down: boolean } | null;
  onSort: (k: string) => void;
  current: string | null;
  keyOf: (r: Rec) => string;
  onSelect: (r: Rec) => void;
  onOpen: (r: Rec) => void;
}) {
  const wantSparks = cols.some((c) => c.kind === "spark");
  const { sparks, watch } = useVisibleSparks();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const row = box.current?.querySelector('tr[aria-selected="true"]');
    if (row && "scrollIntoView" in row) (row as HTMLElement).scrollIntoView({ block: "nearest" });
  }, [current]);
  return (
    <div className="dtable-wrap" ref={box}>
      <table className="dtable" aria-label="Results">
        <thead>
          <tr>
            {cols.map((c) => (
              <th
                key={c.key}
                className={NUMERIC.includes(c.kind) ? "r" : ""}
                title={c.title}
                aria-sort={sort?.key === c.key ? (sort.down ? "descending" : "ascending") : undefined}
              >
                {c.kind === "spark" ? (
                  c.label
                ) : (
                  <button className="th-btn" onClick={() => onSort(c.key)}>
                    {c.label}
                    {sort?.key === c.key && <Icon name={sort.down ? "down" : "up"} size={12} />}
                  </button>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={keyOf(r)} ref={wantSparks ? watch(String(r.ticker)) : undefined} aria-selected={current === keyOf(r)} className={current === keyOf(r) ? "active" : undefined} onClick={() => onSelect(r)} onDoubleClick={() => onOpen(r)}>
              {cols.map((c) => (
                <td key={c.key} className={`${NUMERIC.includes(c.kind) ? "r num" : ""}${c.key === "grade_why" ? " why" : ""}`}>
                  <Cell col={c} rec={r} sparks={sparks} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The phone's rows (the approved mockup): grade, ticker with setup and RVOL, chart, last and change. */
function PhoneRows({ rows, onOpen, page }: { rows: Rec[]; onOpen: (r: Rec) => void; page: Page }) {
  const { sparks, watch } = useVisibleSparks();
  return (
    <ul className="plist screener" aria-label="Results">
      {rows.map((r) => {
        const chg = num(r.chg_pct);
        const grade = typeof r.grade === "string" ? r.grade : "";
        return (
          <li key={`${r.ticker}|${r.scan ?? ""}`} ref={watch(String(r.ticker))}>
            <button className="prow" onClick={() => onOpen(r)} aria-label={`Open ${r.ticker}`}>
              {page === "hits" && (grade ? <GradeBadge grade={grade} /> : <span className="muted badge-gap">–</span>)}
              <span className="pl-main">
                <b>{String(r.ticker)}</b>
                <small className="muted">
                  {[typeof r.scan_label === "string" ? r.scan_label : nameOf(String(r.ticker)), num(r.rvol50) !== null ? `RVOL ${num(r.rvol50)!.toFixed(1)}` : ""].filter(Boolean).join(" · ")}
                </small>
              </span>
              <Sparkline closes={sparks[String(r.ticker)]} />
              <span className="pl-num">
                <span className="num">{(num(r.close)?.toFixed(2) ?? "–")}</span>
                <span className={`num ${chg === null ? "" : chg >= 0 ? "up" : "down"}`}>{chg === null ? "" : formatValue(chg, "pct")}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** Charts: a grid of mini candle charts (the last 60 days), 30 at a time. */
function Charts({ rows, onOpen }: { rows: Rec[]; onOpen: (r: Rec) => void }) {
  const [shown, setShown] = useState(30);
  const list = rows.slice(0, shown);
  const key = list.map((r) => String(r.ticker)).join(",");
  const [sparks, setSparks] = useState<Record<string, Spark>>({});
  useEffect(() => {
    const want = [...new Set(key.split(",").filter(Boolean))].filter((t) => !(t in sparks));
    let live = true;
    for (let i = 0; i < want.length; i += 10) {
      api.sparks(want.slice(i, i + 10), 60).then((s) => live && setSparks((x) => ({ ...x, ...s })), () => {});
    }
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only new tickers are fetched
  }, [key]);
  return (
    <div className="sc-pad">
      <div className="chart-grid" aria-label="Charts">
        {list.map((r) => {
          const t = String(r.ticker);
          const chg = num(r.chg_pct);
          return (
            <button key={`${t}|${r.scan ?? ""}`} className="tile-card" onClick={() => onOpen(r)} aria-label={`Open ${t}`}>
              <div className="top-line">
                {typeof r.grade === "string" && r.grade && <GradeBadge grade={r.grade} />}
                <span className="tk">{t}</span>
                {chg !== null && <span className={`chg num ${chg >= 0 ? "up" : "down"}`}>{formatValue(chg, "pct")}</span>}
              </div>
              <div className="facts">
                <span>{typeof r.scan_label === "string" ? r.scan_label : nameOf(t)}</span>
                {num(r.adr20_pct) !== null && <span>ADR {num(r.adr20_pct)!.toFixed(1)}%</span>}
                {num(r.rs_pct) !== null && <span>RS {num(r.rs_pct)!.toFixed(0)}</span>}
              </div>
              <div className="mini-box">{sparks[t] ? <MiniCandles candles={sparks[t]} label={t} height={96} /> : null}</div>
            </button>
          );
        })}
      </div>
      {rows.length > shown && (
        <div className="row">
          <button onClick={() => setShown((s) => s + 30)}>Show {Math.min(30, rows.length - shown)} more</button>
        </div>
      )}
    </div>
  );
}
