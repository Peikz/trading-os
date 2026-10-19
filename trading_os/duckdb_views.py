"""A DuckDB file with views over the data repo's Parquet (SPEC §2 "Query: DuckDB").

For ad-hoc questions and as the Power BI source (Phase 4, via the DuckDB ODBC driver).
The views read the Parquet files at query time, so the database never goes stale and holds
no data itself. Rebuild it when the data repo moves:

    uv run --group analysis python scripts/build_duckdb.py --data-dir ../trading-os-data
"""

from __future__ import annotations

import argparse
from pathlib import Path

VIEWS = {
    "universe": "data/universe/*/*.parquet",
    "candidates": "data/candidates/*/*.parquet",
    "outcomes": "data/outcomes/*/*.parquet",
    "bars_massive": "data/bars/massive/*/*.parquet",
    "manual_candidates": "data/manual/*/candidates.parquet",
}

HORIZONS = (5, 10, 20, 60)


def signals_with_outcomes_sql(horizons: tuple[int, ...] = HORIZONS) -> str:
    """Candidates with one column set per outcome horizon (SPEC §7)."""
    columns = [
        f"o{h}.close_ret_pct as ret_{h}d, o{h}.max_gain_pct as max_gain_{h}d, "
        f"o{h}.max_drawdown_pct as max_dd_{h}d"
        for h in horizons
    ]
    stops = ", ".join(f"o{h}.hit_order_stop" for h in horizons)
    joins = [
        f"left join (select * from outcomes where horizon = {h}) o{h} using (signal_id)"
        for h in horizons
    ]
    return (
        "create or replace view signals_with_outcomes as select c.*, "
        + ", ".join(columns)
        + f", coalesce({stops}) as hit_order_stop_any from candidates c "
        + " ".join(joins)
    )


def build(data_dir: Path, out: Path) -> list[str]:
    import duckdb  # analysis dependency group only

    data_dir = data_dir.resolve()
    created = []
    with duckdb.connect(str(out)) as con:
        for name, pattern in VIEWS.items():
            files = list(data_dir.glob(pattern))
            if not files:
                con.execute(f"drop view if exists {name}")
                continue
            glob = (data_dir / pattern).as_posix()
            con.execute(
                f"create or replace view {name} as "
                f"select * from read_parquet('{glob}', union_by_name = true)"
            )
            created.append(name)
        snapshots = sorted((data_dir / "data" / "journal").glob("journal_*.parquet"))
        if snapshots:  # the newest snapshot is the journal
            con.execute(
                "create or replace view journal as select * from "
                f"read_parquet('{snapshots[-1].as_posix()}')"
            )
            created.append("journal")
        if {"candidates", "outcomes"} <= set(created):
            con.execute(signals_with_outcomes_sql())
            created.append("signals_with_outcomes")
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the DuckDB views file")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="default: <data-dir>/trading_os.duckdb")
    args = parser.parse_args(argv)
    out = args.out or args.data_dir / "trading_os.duckdb"
    created = build(args.data_dir, out)
    print(f"{out}: views {', '.join(created) or '(none yet: no Parquet found)'}")
    return 0
