"""Grading analysis (Emil, 20 Oct 2026): costs, plan choice and the feature scorecard, all
validated walk-forward by year. Research code for the report and for the grading rules in
config; nothing here runs in the scheduled jobs. Facts, not advice.

Steps, per strategy:

1. Costs (`add_costs`): Saxo's commission on both orders, slippage by the stock's liquidity
   and the kind of order (opening and pre-market fills cost more, stop fills slip a little
   further), borrow for shorts. A trade's cost in R = its cost in % / its stop distance in
   %, so tight stops pay most.
2. Plans (`plan_table`, `walk_forward_plans`): every entry x stop x exit, its net R by
   year. Choosing the best plan on years before Y and scoring it in Y says whether picking
   the best plan carries forward.
3. Scorecard (`fit_scorecard`): every feature cut into buckets (quintiles of the training
   years, its own bucket for missing values, categories as they are); a ridge regression
   of the trade's net R (capped) on the bucket dummies gives points per bucket. Predicted R
   = the training mean + the points of the trade's buckets. Ridge shrinks small buckets
   toward zero, and every number is a plain table that config can hold.
4. Walk-forward (`walk_forward_scores`): fit on the years before Y, score Y, for every Y;
   the grades are judged only on those out-of-sample scores.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CAP = 20.0  # R per trade, like the other studies
FIT_CAP = 10.0  # the scorecard fits on R capped tighter: one runner shouldn't set a bucket

# Saxo, lowest tier, USD account (Emil, 20 Oct 2026). All (proposed).
COSTS: dict[str, Any] = {
    "commission_pct": 0.08,  # per order
    "commission_min_usd": 1.0,
    "slip_by_dvol": [  # (20-day average dollar volume at least, slippage % per side)
        (50e6, 0.05),
        (10e6, 0.10),
        (2e6, 0.25),
        (0.0, 0.50),
    ],
    "min_tick_usd": 0.01,  # half a spread is at least a cent
    "open_mult": 2.0,  # fills in the first minutes of the session
    "offhours_mult": 3.0,  # pre-market and after-hours fills
    "stop_slip_adr": 0.05,  # a stop order fills a little past its level
    "borrow_easy_pct": 1.0,  # yearly borrow for a short: liquid large names ...
    "borrow_hard_pct": 20.0,  # ... and the rest
    "borrow_easy_dvol": 50e6,
    "borrow_easy_price": 10.0,
}
OPEN_ENTRIES = {"open", "orh_5m", "next_open", "next_orb_5m"}
OFFHOURS_ENTRIES = {"ah_1800", "pm_0800", "pm_0915"}
STOP_ENTRIES = {
    "orh_5m",
    "orh_15m",
    "orh_30m",
    "orh_60m",
    "pivot_cross",
    "pivot_1000",
    "next_orb_5m",
    "next_prior_break",
    "turn_green",
}


def load(folder, strategies: Iterable[str] | None = None, columns=None) -> pd.DataFrame:
    """The grading files (`grading_<year>.parquet`) in `folder`, optionally a few strategies
    and columns only (memory)."""
    import pyarrow.dataset as ds

    files = sorted(Path(folder).glob("grading_[0-9][0-9][0-9][0-9].parquet"))
    if not files:
        return pd.DataFrame()
    data = ds.dataset([str(f) for f in files], format="parquet")
    names = set(data.schema.names)
    cols = None if columns is None else [c for c in dict.fromkeys(columns) if c in names]
    filt = ds.field("strategy").isin(list(strategies)) if strategies else None
    df = data.to_table(columns=cols, filter=filt).to_pandas()
    if "session_date" in df:
        df["session_date"] = pd.to_datetime(df["session_date"]).dt.date
        df["year"] = pd.to_datetime(df["session_date"]).dt.year
    return df


def slippage_pct(dvol: np.ndarray, price: np.ndarray, conf: Mapping = COSTS) -> np.ndarray:
    """Per-side slippage in % from the 20-day average dollar volume, at least a cent."""
    dvol = np.nan_to_num(np.asarray(dvol, dtype=float), nan=0.0)
    out = np.full(dvol.shape, conf["slip_by_dvol"][-1][1], dtype=float)
    for floor, pct in reversed(conf["slip_by_dvol"]):
        out = np.where(dvol >= floor, pct, out)
    with np.errstate(divide="ignore", invalid="ignore"):
        tick = conf["min_tick_usd"] / np.asarray(price, dtype=float) * 100
    return np.fmax(out, np.nan_to_num(tick, nan=0.0))


def add_costs(
    df: pd.DataFrame, conf: Mapping = COSTS, days_col: str | None = None, price_col: str = "price"
) -> pd.DataFrame:
    """Per trade: `stop_pct` (stop distance, % of the entry), `cost_pct` (commission on both
    orders, the entry's slippage and a market exit's slippage; borrow too when `days_col` is
    given), `cost_r` (the same in R) and `stop_slip_r` (the extra slip, in R, of an exit by
    the stop: `net_r` charges it only to trades that stopped out). `price_col`: the real
    traded price when known (raw), else the adjusted one."""
    out = df.copy()
    price = out[price_col].to_numpy(dtype=float)
    stop_pct = ((out["price"] - out["stop"]).abs() / out["price"] * 100).to_numpy(dtype=float)
    base = slippage_pct(out.get("d_dvol20", pd.Series(np.nan, index=out.index)), price, conf)
    entry = out["entry"].to_numpy()
    mult = np.where(
        np.isin(entry, list(OFFHOURS_ENTRIES)),
        conf["offhours_mult"],
        np.where(np.isin(entry, list(OPEN_ENTRIES)), conf["open_mult"], 1.0),
    )
    adr_pct = (out["adr_usd"] / out["prev_close"] * 100).to_numpy(dtype=float)
    stop_slip = conf["stop_slip_adr"] * np.nan_to_num(adr_pct, nan=0.0)
    entry_slip = base * mult + np.where(np.isin(entry, list(STOP_ENTRIES)), stop_slip, 0.0)
    cost = 2 * conf["commission_pct"] + entry_slip + base
    if "side" in out and days_col and days_col in out:
        short = out["side"].to_numpy() < 0
        dvol = np.nan_to_num(out.get("d_dvol20", pd.Series(0.0, index=out.index)).to_numpy())
        easy = (dvol >= conf["borrow_easy_dvol"]) & (price >= conf["borrow_easy_price"])
        rate = np.where(easy, conf["borrow_easy_pct"], conf["borrow_hard_pct"])
        days = np.nan_to_num(out[days_col].to_numpy(dtype=float), nan=0.0)
        cost = cost + np.where(short, rate * np.maximum(days, 1) / 252, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["stop_pct"] = stop_pct.astype("float32")
        out["cost_pct"] = cost.astype("float32")
        out["cost_r"] = (cost / stop_pct).astype("float32")
        out["stop_slip_r"] = (stop_slip / stop_pct).astype("float32")
    return out


STOPPED_R = -0.98  # an exit at about -1R (or worse, on a gap) went out by the stop


def net_r(df: pd.DataFrame, exit_name: str, cap: float = CAP) -> pd.Series:
    """Net R of one exit: gross R capped at `cap`, minus the trade's cost in R, and the stop
    order's extra slip when the exit was the stop."""
    r = df[f"r_{exit_name}"].astype(float)
    slip = df["stop_slip_r"].astype(float) if "stop_slip_r" in df else 0.0
    return r.clip(upper=cap) - df["cost_r"].astype(float) - np.where(r <= STOPPED_R, slip, 0.0)


def exits_of(df: pd.DataFrame) -> list[str]:
    return [c[2:] for c in df.columns if c.startswith("r_") and not c.startswith("r_part")]


def stats(r: pd.Series, years: pd.Series) -> dict[str, float]:
    """Trades, mean, median, win %, and the share of years with a positive mean."""
    r = r.dropna()
    if r.empty:
        return {"trades": 0}
    by_year = r.groupby(years.loc[r.index]).mean()
    return {
        "trades": int(len(r)),
        "mean_r": float(r.mean()),
        "median_r": float(r.median()),
        "win_pct": float((r > 0).mean() * 100),
        "years": int(len(by_year)),
        "years_pos": int((by_year > 0).sum()),
        "worst_year_r": float(by_year.min()),
    }


def plan_table(df: pd.DataFrame, min_trades: int = 100) -> pd.DataFrame:
    """Every entry x stop x exit of the strategies in `df`, net of costs."""
    rows = []
    for (strategy, entry, stop), part in df.groupby(["strategy", "entry", "stop_rule"]):
        for name in exits_of(part):
            s = stats(net_r(part, name), part["year"])
            if s.get("trades", 0) >= min_trades:
                rows.append(
                    {"strategy": strategy, "entry": entry, "stop_rule": stop, "exit": name} | s
                )
    return pd.DataFrame(rows)


def walk_forward_plans(df: pd.DataFrame, first_test: int, min_trades: int = 100) -> pd.DataFrame:
    """For each test year: the plan with the best mean net R over the years before it, and
    how that plan did in the test year (per strategy)."""
    rows = []
    years = sorted(df["year"].unique())
    keys = ["strategy", "entry", "stop_rule"]
    for (strategy,), part in df.groupby(["strategy"]):
        per_year = []
        for (entry, stop), plan in part.groupby(keys[1:]):
            for name in exits_of(plan):
                r = net_r(plan, name)
                g = r.groupby(plan["year"]).agg(["sum", "count"])
                g["entry"], g["stop_rule"], g["exit"] = entry, stop, name
                per_year.append(g.reset_index())
        if not per_year:
            continue
        table = pd.concat(per_year, ignore_index=True)
        for y in (y for y in years if y >= first_test):
            train = (
                table[table["year"] < y]
                .groupby(["entry", "stop_rule", "exit"])[["sum", "count"]]
                .sum()
            )
            train = train[train["count"] >= min_trades]
            if train.empty:
                continue
            best = (train["sum"] / train["count"]).idxmax()
            test = table[
                (table["year"] == y)
                & (table["entry"] == best[0])
                & (table["stop_rule"] == best[1])
                & (table["exit"] == best[2])
            ]
            n = int(test["count"].sum())
            rows.append(
                {
                    "strategy": strategy,
                    "year": y,
                    "entry": best[0],
                    "stop_rule": best[1],
                    "exit": best[2],
                    "train_r": float(train.loc[best, "sum"] / train.loc[best, "count"]),
                    "test_trades": n,
                    "test_r": float(test["sum"].sum() / n) if n else np.nan,
                }
            )
    return pd.DataFrame(rows)


@dataclass
class Feature:
    """One feature's buckets: numeric edges (quintiles of the training years) or the
    categories seen in training; missing values get their own bucket."""

    name: str
    edges: list[float] | None = None
    categories: list[Any] | None = None

    def labels(self, values: pd.Series) -> pd.Series:
        if self.edges is not None:
            v = pd.to_numeric(values, errors="coerce")
            idx = np.searchsorted(np.asarray(self.edges), v.to_numpy(dtype=float), side="right")
            out = pd.Series(idx.astype(str), index=values.index)
            return out.where(v.notna(), "na")
        out = values.astype(object).where(values.notna(), "na").astype(str)
        known = {str(c) for c in self.categories or []}
        return out.where(out.isin(known | {"na"}), "other")

    def describe(self, label: str) -> str:
        if self.edges is None or label in ("na", "other"):
            return f"{self.name} = {label}"
        i = int(label)
        lo = f"{self.edges[i - 1]:.4g}" if i > 0 else "-inf"
        hi = f"{self.edges[i]:.4g}" if i < len(self.edges) else "inf"
        return f"{lo} <= {self.name} < {hi}"


def make_feature(name: str, train: pd.Series, bins: int = 5, max_categories: int = 12) -> Feature:
    numeric = pd.api.types.is_numeric_dtype(train) and not pd.api.types.is_bool_dtype(train)
    values = train.dropna()
    if numeric and values.nunique() > max_categories:
        qs = np.unique(np.quantile(values.astype(float), np.linspace(0, 1, bins + 1)[1:-1]))
        return Feature(name, edges=[float(q) for q in qs])
    cats = values.astype(object).astype(str).value_counts().index[:max_categories].tolist()
    return Feature(name, categories=cats)


@dataclass
class Scorecard:
    """Points per bucket; predicted R = intercept + the trade's points."""

    intercept: float
    features: list[Feature]
    points: dict[str, dict[str, float]] = field(default_factory=dict)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)

    def predict(self, df: pd.DataFrame) -> pd.Series:
        total = pd.Series(self.intercept, index=df.index, dtype=float)
        for f in self.features:
            labels = f.labels(df[f.name]) if f.name in df else pd.Series("na", index=df.index)
            total += labels.map(self.points.get(f.name, {})).fillna(0.0).astype(float)
        return total

    def table(self) -> pd.DataFrame:
        rows = []
        for f in self.features:
            for label, pts in self.points.get(f.name, {}).items():
                rows.append(
                    {
                        "feature": f.name,
                        "bucket": f.describe(label),
                        "label": label,
                        "points": pts,
                        "trades": self.counts.get(f.name, {}).get(label, 0),
                    }
                )
        return pd.DataFrame(rows)


def fit_scorecard(
    train: pd.DataFrame,
    target: pd.Series,
    names: Sequence[str],
    l2: float = 300.0,
    bins: int = 5,
    min_bucket: int = 50,
) -> Scorecard:
    """Ridge regression of `target` on the bucket dummies of `names` (buckets from `train`).
    Buckets with fewer than `min_bucket` training trades get no points."""
    y = target.astype(float).clip(upper=FIT_CAP).to_numpy()
    ok = ~np.isnan(y)
    train, y = train[ok], y[ok]
    feats = [make_feature(n, train[n], bins) for n in names if n in train]
    blocks, columns, counts = [], [], {}
    for f in feats:
        labels = f.labels(train[f.name])
        vc = labels.value_counts()
        counts[f.name] = {str(k): int(v) for k, v in vc.items()}
        for label in vc.index[vc >= min_bucket]:
            blocks.append((labels == label).to_numpy(dtype=np.float32))
            columns.append((f.name, str(label)))
    mean = float(y.mean()) if len(y) else 0.0
    card = Scorecard(mean, feats, counts=counts)
    if not blocks:
        return card
    x = np.stack(blocks, axis=1)
    x_mean = x.mean(axis=0)
    xc = x - x_mean
    beta = np.linalg.solve(xc.T @ xc + l2 * np.eye(x.shape[1]), xc.T @ (y - mean))
    card.intercept = float(mean - x_mean @ beta)
    for (name, label), b in zip(columns, beta, strict=True):
        card.points.setdefault(name, {})[label] = float(b)
    return card


def _candidates(values: pd.Series, max_categories: int = 12):
    """(label, numeric series) pairs to test: the feature itself when numeric, else one 0/1
    series per category."""
    numeric = pd.api.types.is_numeric_dtype(values) and not pd.api.types.is_bool_dtype(values)
    if numeric and values.nunique() > 2:
        return [(None, values.astype(float))]
    cats = values.dropna().astype(object).astype(str).value_counts().index[:max_categories]
    text = values.astype(object).where(values.notna(), None).astype(str)
    return [(c, (text == c).astype(float).where(values.notna())) for c in cats]


def stable_features(
    train: pd.DataFrame,
    target: pd.Series,
    names: Sequence[str],
    min_share: float = 0.7,
    min_rho: float = 0.02,
    max_features: int = 8,
    min_years: int = 3,
) -> pd.DataFrame:
    """Features whose rank correlation with `target` keeps its sign in at least `min_share`
    of the training years (each year with 30+ trades), strongest first, at most
    `max_features`. Categories count through their own 0/1 series; a feature is kept when
    any of its categories is. Returns name, mean rho, sign share, years."""
    rows = []
    t = target.astype(float).clip(upper=FIT_CAP)
    for name in names:
        if name not in train:
            continue
        for label, x in _candidates(train[name]):
            rhos = []
            for _, idx in train.groupby("year").groups.items():
                xs, ts = x.loc[idx], t.loc[idx]
                ok = xs.notna() & ts.notna()
                if ok.sum() >= 30 and xs[ok].nunique() > 1:
                    rhos.append(xs[ok].rank().corr(ts[ok].rank()))
            rhos = [r for r in rhos if r == r]
            if len(rhos) < min_years:
                continue
            mean = float(np.mean(rhos))
            share = float(np.mean(np.sign(rhos) == np.sign(mean)))
            rows.append(
                {"name": name, "label": label, "rho": mean, "share": share, "years": len(rhos)}
            )
    table = pd.DataFrame(rows, columns=["name", "label", "rho", "share", "years"])
    keep = table[(table["share"] >= min_share) & (table["rho"].abs() >= min_rho)].copy()
    keep["strength"] = keep["rho"].abs() * keep["share"]
    keep = keep.sort_values("strength", ascending=False).drop_duplicates("name")
    return keep.head(max_features).reset_index(drop=True)


def walk_forward_scores(
    df: pd.DataFrame,
    target: pd.Series,
    names: Sequence[str],
    first_test: int,
    min_train_years: int = 3,
    select: Mapping[str, Any] | None = None,
    chosen: dict | None = None,
    **fit_args,
) -> pd.Series:
    """Out-of-sample predicted R: every year from `first_test` scored by a scorecard fitted
    on the years before it only (NaN for the years before `first_test`). With `select`
    (arguments of `stable_features`), the features are picked on those training years too;
    `chosen` collects each test year's picks."""
    pred = pd.Series(np.nan, index=df.index, dtype=float)
    for y in sorted(df["year"].unique()):
        if y < first_test:
            continue
        past = df["year"] < y
        if df.loc[past, "year"].nunique() < min_train_years:
            continue
        use = list(names)
        if select is not None:
            use = stable_features(df[past], target[past], names, **select)["name"].tolist()
            if chosen is not None:
                chosen[y] = use
        card = fit_scorecard(df[past], target[past], use, **fit_args)
        now = df["year"] == y
        pred[now] = card.predict(df[now])
    return pred


GRADES = ("A+", "A", "B", "C")


def grade(pred: pd.Series, cutoffs: Mapping[str, float]) -> pd.Series:
    """A+/A/B/C from predicted R: the first grade whose cutoff the prediction reaches."""
    out = pd.Series("C", index=pred.index, dtype=object)
    for g in reversed(GRADES[:-1]):
        out = out.where(~(pred >= cutoffs[g]), g)
    return out.where(pred.notna(), None)


def grade_stats(df: pd.DataFrame, grades: pd.Series, r: pd.Series) -> pd.DataFrame:
    rows = []
    for g in GRADES:
        mask = grades == g
        rows.append({"grade": g} | stats(r[mask], df["year"]))
    return pd.DataFrame(rows)
