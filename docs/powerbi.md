# Power BI over the data repo (Phase 4)

Everything lives as Parquet in the private `trading-os-data` repo. Two ways in:

## A. DuckDB views (recommended)

1. Build the views file next to the data (rebuild after moving the folder):

   ```bash
   uv run --group analysis python scripts/build_duckdb.py --data-dir ../trading-os-data
   ```

2. Install the DuckDB ODBC driver (duckdb.org → ODBC) and create a DSN that points at
   `trading-os-data/trading_os.duckdb` (read-only).
3. Power BI Desktop → Get Data → ODBC → that DSN. The views read the Parquet files at
   query time, so a refresh picks up new runs without rebuilding.

Views: `universe`, `candidates`, `outcomes`, `signals_with_outcomes`, `journal`, `breadth`,
`watchlists`, `market_light_count`, `bars_massive`, `manual_candidates`.

## B. Parquet folders

Power BI Desktop → Get Data → Folder → `trading-os-data/data/candidates` (and so on), then
Combine → Parquet. Simpler, but each table is a separate folder query, and columns added
later need a refresh of the combine step.

## Suggested model

| Table | Key | Relates to |
|---|---|---|
| candidates | signal_id | outcomes (1:many by signal_id), journal (signal_id) |
| outcomes | signal_id + horizon | candidates |
| journal | trade_id | candidates via signal_id |
| breadth | session_date | a date table |

Add a date table on `session_date` and mark it as the date table.

Example measures (DAX):

```
Signals      = DISTINCTCOUNT ( candidates[signal_id] )
Win rate 10d = DIVIDE (
    CALCULATE ( COUNTROWS ( outcomes ), outcomes[horizon] = 10, outcomes[close_ret_pct] > 0 ),
    CALCULATE ( COUNTROWS ( outcomes ), outcomes[horizon] = 10 ) )
Avg R        = AVERAGE ( journal[r_multiple] )
Expectancy   = AVERAGE ( journal[pnl] )
```

The views and this file contain no data; the numbers stay in the private repo.
