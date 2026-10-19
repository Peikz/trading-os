# TradingView fields

Verified against live data on 2026-10-19 with `scripts/verify_fields.py`.
Source: `tradingview-screener` (no login, 15-min delayed), market `america`.
This file holds field names and aggregate checks only, never tickers or prices.

Universe query matched 4523 rows and returned 4523 (no truncation).

## Findings

- The package's default filter keeps primary listings only (`is_primary`). That drops second share classes (e.g. class B shares), interlisted Canadian stocks and about 60 % of ADRs, so the universe query replaces it with SPEC §4's explicit exclusions. `is_primary` is stored.
- Exclusions use `type` (stock, dr) and `typespecs` (preferred, unit, warrant, right, etf, etn). ADRs have empty `typespecs`.
- `gap` and `change` are percent and match open and close against close - change_abs.
- `average_volume_Nd_calc` includes today. RVOL removes it: (N x avg - volume) / (N - 1).
- Prior-bar values exist as `close[1]`, `volume[1]`, `high[1]`, `low[1]`. `close[1]` matches close - change_abs, so `[1]` is the previous daily bar.
- Quarterly history: `total_revenue_fq_h` (reported revenue) and `earnings_per_share_diluted_fq_h` hold 32 quarters, latest first, so previous-quarter YoY growth is computable (SPEC §11.2). Index 0 vs 4 reproduces TradingView's latest-quarter YoY (EPS with |year-ago| as the base). `revenues_fq_h` is the analyst-estimates series (oldest first, forecasts appended) and is not used.
- Offsets beyond `[2]` (e.g. `close[5]`, `SMA20[5]`) come back empty: TradingView serves only two prior bars, not enough for 10-day returns, MA slopes or 5/10-day breadth ratios.

## Fields used by the jobs

| Column | TradingView field | dtype | non-null % | Notes |
|---|---|---|---|---|
| `ticker` | `name` | str | 100.0 |  |
| `exchange` | `exchange` | str | 100.0 |  |
| `type` | `type` | str | 100.0 |  |
| `typespecs` | `typespecs` | str | 100.0 |  |
| `is_primary` | `is_primary` | bool | 100.0 |  |
| `country` | `country` | str | 100.0 | company country (Market Light scan count: Country USA) |
| `sector` | `sector` | str | 100.0 |  |
| `industry` | `industry` | str | 100.0 |  |
| `open` | `open` | float64 | 100.0 |  |
| `high` | `high` | float64 | 100.0 |  |
| `low` | `low` | float64 | 100.0 |  |
| `close` | `close` | float64 | 100.0 |  |
| `volume` | `volume` | int64 | 100.0 |  |
| `prev_close` | `close[1]` | float64 | 100.0 | previous daily bar's close |
| `prev_volume` | `volume[1]` | float64 | 100.0 | previous daily bar's volume (Momentum Burst: volume > prior day) |
| `chg_pct` | `change` | float64 | 100.0 | percent (12.3 = 12.3 %), close vs prior close |
| `chg_abs` | `change_abs` | float64 | 100.0 | price units, close - prior close |
| `gap_pct` | `gap` | float64 | 100.0 | percent, open vs prior close |
| `market_cap` | `market_cap_basic` | float64 | 100.0 | USD |
| `float_shares` | `float_shares_outstanding` | float64 | 97.8 |  |
| `rvol10_tv` | `relative_volume_10d_calc` | float64 | 99.8 | TradingView relative volume, 10-day base |
| `high_all_tv` | `High.All` | float64 | — | All-time high (19 Oct 2026), for "at all-time high" in the facts |
| `rvol_at_time_tv` | `relative_volume_intraday\|5` | float64 | — | Relative volume at this time of day (5-minute bars); the EP9M pace input. Present 19 Oct; values to check on the first live intraday run |
| `avg_volume_10d_tv` | `average_volume_10d_calc` | float64 | 99.8 |  |
| `avg_volume_30d_tv` | `average_volume_30d_calc` | float64 | 99.2 |  |
| `avg_volume_60d_tv` | `average_volume_60d_calc` | float64 | 97.5 |  |
| `avg_volume_90d_tv` | `average_volume_90d_calc` | float64 | 96.3 |  |
| `avg_dollar_volume_30d_tv` | `AvgValue.Traded_30d` | float64 | 99.2 | USD per day |
| `ma10` | `SMA10` | float64 | 99.8 |  |
| `ma20` | `SMA20` | float64 | 99.5 |  |
| `ma50` | `SMA50` | float64 | 98.3 |  |
| `ma200` | `SMA200` | float64 | 92.2 |  |
| `high_52w` | `price_52_week_high` | float64 | 100.0 |  |
| `perf_1m_tv` | `Perf.1M` | float64 | 100.0 | percent |
| `perf_3m_tv` | `Perf.3M` | float64 | 100.0 | percent |
| `perf_6m_tv` | `Perf.6M` | float64 | 100.0 | percent |
| `adr14_usd_tv` | `ADR` | float64 | 99.6 | price units, 14-day average day range (not SPEC's ADR(20) %) |
| `earnings_date_last` | `earnings_release_date` | datetime64[s, UTC] | 87.7 | unix seconds -> UTC timestamp |
| `earnings_date_next` | `earnings_release_next_date` | datetime64[s, UTC] | 87.5 | unix seconds -> UTC timestamp |
| `rev_growth_q` | `total_revenue_yoy_growth_fq` | float64 | 81.6 | percent, latest fiscal quarter YoY |
| `eps_growth_q` | `earnings_per_share_diluted_yoy_growth_fq` | float64 | 81.3 | percent, latest fiscal quarter YoY (diluted EPS) |
| `revenue_ttm` | `total_revenue_ttm` | float64 | 93.6 | USD, trailing 12 months |
| `pm_change_pct` | `premarket_change` | float64 | 53.8 | percent, pre-market vs prior close |
| `pm_gap_pct` | `premarket_gap` | float64 | 53.8 | percent |
| `pm_volume` | `premarket_volume` | float64 | 53.8 |  |
| `pm_price` | `premarket_close` | float64 | 53.8 | last pre-market price |
| `ah_change_pct` | `postmarket_change` | float64 | 91.9 | percent, post-market vs close |
| `ah_volume` | `postmarket_volume` | float64 | 91.9 |  |
| `revenue_q_hist` | `total_revenue_fq_h` | object | 97.6 | weekly job only: reported quarterly revenue, latest first |
| `eps_q_hist` | `earnings_per_share_diluted_fq_h` | object | 97.6 | weekly job only: diluted EPS per quarter, latest first |

## Checks

- tickers unique: True (0 dups)
- chg_pct vs close/(close-chg_abs): 100.0% of 4521 rows within 0.05pp
- gap_pct vs open/(close-chg_abs): 100.0% of 4521 rows within 0.05pp
- prev_close vs close-chg_abs: 100.0% of 4521 rows within 0.01pp
- rvol10_tv / (volume / avg_volume_10d_tv as given) on 62 rows with rvol10_tv > 5: median 1.786, p10 1.451, p90 3.197
- rvol10_tv / (volume / avg_volume_10d_tv today removed) on 62 rows with rvol10_tv > 5: median 1.047, p10 0.932, p90 1.108
- max volume / avg_volume_10d_tv: 9.1 (<= 10 means today is included). Conclusion: average_volume_Nd_calc includes today; metrics.py removes it for RVOL.
- rev_growth_q vs revenue_q_hist[0] / [4]: 100.0% of 3692 rows within 0.1pp
- eps_growth_q vs eps_q_hist[0] vs [4] (|base|): 100.0% of 3678 rows within 0.5pp
- avg_dollar_volume_30d_tv / (close x avg_volume_30d_tv): median 1.022
- rows with close x volume >= $5M: 2880
- earnings_date_next range: 2026-10-19 .. 2027-05-24

## Probed, not used yet

| Field | non-null % (200 largest) | Python type |
|---|---|---|
| `high[1]` | 100.0 | float64 |
| `low[1]` | 100.0 | float64 |
| `revenues_fq_h` | 100.0 | list[33] |
| `earnings_per_share_diluted_fq_h` | 97.0 | list[32] |
| `total_revenue_yoy_growth_fq_h` | 0.0 | - |
| `postmarket_close` | 100.0 | float64 |
| `country` | 100.0 | str |
| `Perf.W` | 100.0 | float64 |
| `Perf.Y` | 100.0 | float64 |
| `High.1M` | 100.0 | float64 |
| `High.3M` | 100.0 | float64 |
