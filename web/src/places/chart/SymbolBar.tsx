// The Chart's top bar: step arrows, the ticker with its grade, last price and change, D / W / M,
// the Indicators and Lines popovers, and "Today's hits · 3 of 9". On a phone it becomes a
// header line (‹ ticker last change ›) with the details under it; D/W/M, Indicators and Lines
// move to the tools row under the chart (ToolsRow).
import type { ChartData, ChartListRow, ChartQuery } from "../../api";
import { GradeBadge } from "../../components/Card";
import { type Tool } from "../../components/DrawChart";
import { Icon } from "../../ui/Icon";
import { Segmented, usePopover } from "../../ui/kit";
import { WatchButton } from "../today/WatchNote";

export const LINES = ["MA10", "MA20", "MA50", "MA200", "EMA9", "EMA21"];
const SPANS = ["3M", "6M", "1Y", "2Y", "All"];
const FRAMES = [["Daily", "D"], ["Weekly", "W"], ["Monthly", "M"]] as const;
const TOOLS: [Tool, string, string][] = [
  ["none", "pan", "Pan and zoom"],
  ["draw", "draw", "Draw a trend line (two clicks)"],
  ["move", "move", "Move a line's end (drag)"],
  ["erase", "erase", "Delete the line you click"],
];

const pct = (x: number | null) => (x === null ? "" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}%`);

/** Last and % change: the list's snapshot numbers, else the chart's last two bars. */
export function quote(row: ChartListRow | undefined, data: ChartData | null, symbol: string) {
  if (row && row.last !== null) return { last: row.last, chg: row.chg_pct };
  const c = data && data.ticker === symbol ? data.candles : [];
  if (c.length === 0) return { last: null, chg: null };
  const last = c[c.length - 1].close;
  return { last, chg: c.length > 1 ? (last / c[c.length - 2].close - 1) * 100 : null };
}

export interface BarProps {
  symbol: string;
  row: ChartListRow | undefined;
  data: ChartData | null;
  q: ChartQuery;
  setQ: (f: (q: ChartQuery) => ChartQuery) => void;
  position: string;
  canPrev: boolean;
  canNext: boolean;
  onStep: (by: 1 | -1) => void;
  watching: boolean;
  onWatch: () => void;
  sideOpen: boolean;
  onSide: () => void;
}

function Indicators({ q, setQ }: Pick<BarProps, "q" | "setQ">) {
  const { open, setOpen, ref } = usePopover();
  const toggle = (l: string) =>
    setQ((x) => ({ ...x, lines: x.lines.includes(l) ? x.lines.filter((y) => y !== l) : [...x.lines, l] }));
  return (
    <div className="popover-wrap" ref={ref}>
      <button aria-expanded={open} onClick={() => setOpen(!open)}>
        Indicators
        <Icon name="down" size={14} />
      </button>
      {open && (
        <div className="popover left" role="dialog" aria-label="Indicators">
          <h4>Moving averages</h4>
          <div className="check-grid">
            {LINES.map((l) => (
              <label key={l} className="check">
                <input type="checkbox" checked={q.lines.includes(l)} onChange={() => toggle(l)} />
                {l}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Lines({ data, q, setQ }: Pick<BarProps, "data" | "q" | "setQ">) {
  const { open, setOpen, ref } = usePopover();
  const flag = (k: "hits" | "fills" | "levels", v: boolean) => setQ((x) => ({ ...x, [k]: v }));
  const anchor = (name: string) =>
    setQ((x) => ({ ...x, anchors: x.anchors.includes(name) ? x.anchors.filter((y) => y !== name) : [...x.anchors, name] }));
  return (
    <div className="popover-wrap" ref={ref}>
      <button aria-expanded={open} onClick={() => setOpen(!open)}>
        Lines
        <Icon name="down" size={14} />
      </button>
      {open && (
        <div className="popover left" role="dialog" aria-label="Lines">
          <h4>On the chart</h4>
          <div className="check-grid">
            {(["levels", "hits", "fills"] as const).map((k) => (
              <label key={k} className="check">
                <input type="checkbox" checked={q[k]} onChange={(e) => flag(k, e.target.checked)} />
                {{ levels: "Pivot and stops", hits: "Scan hits", fills: "My trades" }[k]}
              </label>
            ))}
          </div>
          <h4>Show</h4>
          <Segmented label="Show" options={SPANS} value={q.span} onPick={(v) => setQ((x) => ({ ...x, span: v }))} />
          <h4>History</h4>
          <Segmented
            label="History"
            options={[["2y", "2 years"], ["10y", "10 years"]] as const}
            value={q.period as "2y" | "10y"}
            onPick={(v) => setQ((x) => ({ ...x, period: v }))}
          />
          {data && Object.keys(data.quick_anchors).length > 0 && (
            <>
              <h4>Anchored VWAP from</h4>
              <div className="pills" role="group" aria-label="Anchored VWAP from">
                {Object.entries(data.quick_anchors).map(([name, day]) => (
                  <button key={name} title={day} className={q.anchors.includes(name) ? "on" : ""} onClick={() => anchor(name)}>
                    {name}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function Frames({ q, setQ }: Pick<BarProps, "q" | "setQ">) {
  return (
    <Segmented
      label="Bars"
      options={FRAMES.map(([v, text]) => [v, text] as const)}
      value={q.timeframe as "Daily"}
      onPick={(v) => setQ((x) => ({ ...x, timeframe: v }))}
    />
  );
}

export function SymbolBar(p: BarProps) {
  const { last, chg } = quote(p.row, p.data, p.symbol);
  const dir = chg === null ? "" : chg >= 0 ? "up" : "down";
  return (
    <header className="ws-bar">
      <div className="step">
        <button className="icon-btn" aria-label="Previous stock" disabled={!p.canPrev} onClick={() => p.onStep(-1)}>
          <Icon name="left" />
        </button>
        <button className="icon-btn" aria-label="Next stock" disabled={!p.canNext} onClick={() => p.onStep(1)}>
          <Icon name="right" />
        </button>
      </div>
      <span className="ticker">{p.symbol || "–"}</span>
      {p.symbol && <WatchButton compact watching={p.watching} onToggle={p.onWatch} />}
      {p.row?.grade && <GradeBadge grade={p.row.grade} />}
      <span className="num price">{last === null ? "" : last.toFixed(2)}</span>
      <span className={`num chg ${dir}`}>{pct(chg)}</span>
      <span className="bar-meta">
        {p.row?.setup}
        {p.row?.rvol != null && <span className="num"> · RVOL {p.row.rvol.toFixed(1)}</span>}
      </span>
      <span className="bar-controls">
        <Frames q={p.q} setQ={p.setQ} />
        <Indicators q={p.q} setQ={p.setQ} />
        <Lines data={p.data} q={p.q} setQ={p.setQ} />
      </span>
      <span className="grow" />
      <span className="position muted num" aria-live="polite">
        {p.position}
      </span>
      <button className="ghost icon-btn" aria-label={p.sideOpen ? "Hide the list" : "Show the list"} aria-expanded={p.sideOpen} onClick={p.onSide}>
        <Icon name="table" />
      </button>
    </header>
  );
}

/** The phone's header: ‹ ticker last change › and a line of facts under it. */
export function PhoneHeader(p: BarProps) {
  const { last, chg } = quote(p.row, p.data, p.symbol);
  const dir = chg === null ? "" : chg >= 0 ? "up" : "down";
  return (
    <header className="ws-phone-head">
      <div className="line">
        <button className="icon-btn" aria-label="Previous stock" disabled={!p.canPrev} onClick={() => p.onStep(-1)}>
          <Icon name="left" size={22} />
        </button>
        <span className="ticker">{p.symbol || "–"}</span>
        <span className="num price">{last === null ? "" : last.toFixed(2)}</span>
        <span className={`num chg ${dir}`}>{pct(chg)}</span>
        {p.symbol && <WatchButton compact watching={p.watching} onToggle={p.onWatch} />}
        <span className="grow" />
        <button className="icon-btn" aria-label="Next stock" disabled={!p.canNext} onClick={() => p.onStep(1)}>
          <Icon name="right" size={22} />
        </button>
      </div>
      <div className="facts muted">
        {p.row?.grade && <GradeBadge grade={p.row.grade} />}
        {p.row?.setup && <span>{p.row.setup}</span>}
        {p.row?.rvol != null && <span className="num">RVOL {p.row.rvol.toFixed(1)}</span>}
        <span className="grow" />
        <span className="num">{p.position}</span>
      </div>
    </header>
  );
}

/** Drawing tools: the vertical rail on a desktop, a row under the chart on a phone. */
export function ToolRail({ tool, onTool, enabled }: { tool: Tool; onTool: (t: Tool) => void; enabled: boolean }) {
  if (!enabled) return <div className="ws-rail" />;
  return (
    <div className="ws-rail seg" role="group" aria-label="Tools">
      {TOOLS.map(([id, icon, title]) => (
        <button key={id} title={title} aria-label={title} aria-pressed={tool === id} className={tool === id ? "on" : ""} onClick={() => onTool(id)}>
          <Icon name={icon} size={18} />
        </button>
      ))}
    </div>
  );
}

export function ToolsRow(p: Pick<BarProps, "q" | "setQ" | "data"> & { tool: Tool; onTool: (t: Tool) => void; enabled: boolean }) {
  return (
    <div className="ws-tools-row">
      <Frames q={p.q} setQ={p.setQ} />
      <Indicators q={p.q} setQ={p.setQ} />
      <Lines data={p.data} q={p.q} setQ={p.setQ} />
      <span className="grow" />
      <ToolRail tool={p.tool} onTool={p.onTool} enabled={p.enabled} />
    </div>
  );
}
