// Today's chart: day / week / month bars, one "Indicators" menu instead of a row of pills, the
// plan's entry and stop as labelled lines, and the stock's full chart (drawing, AVWAPs, minute
// bars, notes) one click away in Stocks.
import { useEffect, useState } from "react";
import { api, type Bars, INDICATORS, type Timeframe } from "../../api";
import { CandleChart } from "../../components/CandleChart";
import { stockLink } from "../../routes";
import { Icon } from "../../ui/Icon";
import { Segmented, usePopover } from "../../ui/kit";

export const TIMEFRAMES: Timeframe[] = ["1D", "1W", "1M"];
const TF_WORDS: Record<Timeframe, string> = { "1D": "Daily bars", "1W": "Weekly bars", "1M": "Monthly bars" };

export function IndicatorMenu({ picked, onChange }: { picked: string[]; onChange: (p: string[]) => void }) {
  const { open, setOpen, ref } = usePopover();
  return (
    <div className="menu-wrap" ref={ref}>
      <button aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name="sliders" size={16} />
        Indicators{picked.length ? ` (${picked.length})` : ""}
      </button>
      {open && (
        <div className="menu" role="group" aria-label="Indicators">
          {INDICATORS.map((name) => (
            <label key={name}>
              <input
                type="checkbox"
                checked={picked.includes(name)}
                onChange={() =>
                  onChange(picked.includes(name) ? picked.filter((x) => x !== name) : [...picked, name])
                }
              />
              {name}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function FocusChart({
  ticker,
  levels,
  anchor,
  tf,
  onTf,
  picked,
  onPicked,
  price,
  change,
  height = 460,
}: {
  ticker: string;
  levels: Record<string, number>;
  anchor: string | null;
  tf: Timeframe;
  onTf: (tf: Timeframe) => void;
  picked: string[];
  onPicked: (p: string[]) => void;
  price?: number | null;
  change?: number | null;
  height?: number;
}) {
  const [bars, setBars] = useState<Bars | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = picked.join(",");

  useEffect(() => {
    let live = true;
    setError(null);
    api.bars(ticker, tf, key ? key.split(",") : [], anchor).then(
      (b) => live && setBars(b),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [ticker, tf, key, anchor]);

  return (
    <section aria-label={`${ticker} chart`}>
      <div className="chart-head">
        <span className="ticker">{ticker}</span>
        {typeof price === "number" && <span className="price num">{price.toFixed(2)}</span>}
        {typeof change === "number" && (
          <span className={`num ${change >= 0 ? "up" : "down"}`}>
            {change >= 0 ? "+" : ""}
            {change.toFixed(1)}%
          </span>
        )}
        <div className="tools">
          <Segmented label="Bars" options={TIMEFRAMES.map((t) => [t, t] as const)} value={tf} onPick={onTf} />
          <IndicatorMenu picked={picked} onChange={onPicked} />
          <a href={stockLink(ticker)} className="muted" title="Drawing tools, AVWAPs, minute bars and notes">
            Full chart
          </a>
        </div>
      </div>
      {error && <p className="error">Chart: {error}</p>}
      {!error && (!bars || bars.ticker !== ticker.toUpperCase()) ? (
        <div className="chart" style={{ height }} aria-busy="true" />
      ) : (
        bars && (
          <CandleChart
            bars={bars}
            levels={levels}
            title={TF_WORDS[tf]}
            height={height}
            showBars={tf === "1D" ? 130 : tf === "1W" ? 80 : 24}
          />
        )
      )}
    </section>
  );
}
