// The Screener's parts (trading_os/screens.py), used by the Stocks place: a filter's editor, a
// filter in words for its chip, the Today link that flips through a screen's stocks, and one
// scan hit's grading form. A screen is a list to look at: no grade, no buy.
import { useEffect, useState } from "react";
import { api, type Filter, type ScreenerMeta } from "../api";
import { GradeForm } from "../components/GradeForm";
import { plain } from "../plain";
import { Icon } from "../ui/Icon";

/** The Today link that flips through a screen's stocks (app/board.py reads the same). */
export function flipLink(name: string, tickers: string[]): string {
  const q = new URLSearchParams({ screen: name, t: tickers.join(",") });
  return `?${q}#/today`;
}

/** A filter in words, for its chip: `Daily range % >= 4`, `Sector is Tech, Energy`. */
export function describeFilter(meta: ScreenerMeta, f: Filter): string {
  const label = plain(meta.fields[f.field]?.label ?? f.field).text;
  const v = f.value;
  if (meta.fields[f.field]?.kind === "bool") return `${label}: ${f.op}`;
  if (Array.isArray(v)) {
    if (f.op === "between") return `${label} ${v[0] ?? "…"} to ${v[1] ?? "…"}`;
    return `${label} ${f.op} ${v.length ? v.join(", ") : "…"}`;
  }
  return `${label} ${f.op} ${v ?? "…"}`;
}

export function FilterRow({
  meta,
  fields,
  filter,
  onChange,
  onRemove,
}: {
  meta: ScreenerMeta;
  fields: string[];
  filter: Filter;
  onChange: (f: Filter) => void;
  onRemove: () => void;
}) {
  const kind = meta.fields[filter.field]?.kind ?? "num";
  const ops = meta.ops[kind];
  const [options, setOptions] = useState<string[]>([]);
  useEffect(() => {
    if (kind === "text") api.options(filter.field).then(setOptions, () => setOptions([]));
  }, [kind, filter.field]);

  const num = (v: string): number | null => (v === "" ? null : Number(v));
  const pair = Array.isArray(filter.value) ? filter.value : [null, null];

  return (
    <div className="row filter">
      <select
        aria-label="Field"
        value={filter.field}
        onChange={(e) => {
          const k = meta.fields[e.target.value].kind;
          const first = meta.ops[k][0];
          onChange({ field: e.target.value, op: first, value: k === "text" ? [] : null });
        }}
      >
        {fields.map((f) => (
          <option key={f} value={f}>
            {meta.fields[f].group} · {plain(meta.fields[f].label).text}
          </option>
        ))}
      </select>
      <select
        aria-label="Operator"
        value={filter.op}
        onChange={(e) => onChange({ ...filter, op: e.target.value, value: null })}
      >
        {ops.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
      {filter.op === "between" ? (
        <>
          <input
            aria-label="From"
            type="number"
            value={(pair[0] as number | null) ?? ""}
            onChange={(e) => onChange({ ...filter, value: [num(e.target.value), pair[1]] })}
          />
          <input
            aria-label="To"
            type="number"
            value={(pair[1] as number | null) ?? ""}
            onChange={(e) => onChange({ ...filter, value: [pair[0], num(e.target.value)] })}
          />
        </>
      ) : filter.op.startsWith("is ") && kind === "text" ? (
        <select
          aria-label="Values"
          multiple
          value={(filter.value as string[] | null) ?? []}
          onChange={(e) =>
            onChange({
              ...filter,
              value: Array.from(e.target.selectedOptions, (o) => o.value),
            })
          }
        >
          {options.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      ) : kind === "bool" ? null : (
        <input
          aria-label="Value"
          type="number"
          value={(filter.value as number | null) ?? ""}
          onChange={(e) => onChange({ ...filter, value: num(e.target.value) })}
        />
      )}
      <button className="ghost icon-btn" onClick={onRemove} title="Remove this filter" aria-label="Remove filter">
        <Icon name="x" size={16} />
      </button>
    </div>
  );
}

/** One scan hit's grading form (grade, notes, tags, screenshots), as under the Streamlit table. */
export function HitGrading({
  ticker,
  signalId,
  scanLabel,
}: {
  ticker: string;
  signalId: string | undefined;
  scanLabel: string;
}) {
  return (
    <section>
      <h3>Grade this hit</h3>
      {signalId ? (
        <GradeForm kind="signal" refId={signalId} title={`Grade ${ticker} · ${scanLabel}`} />
      ) : (
        <p className="muted">This hit has no signal id to grade.</p>
      )}
    </section>
  );
}
