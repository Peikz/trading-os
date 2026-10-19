"""`python -m trading_os.intraday_cli ...` (the intraday study job's entry point)."""

from trading_os.intraday_study import main

if __name__ == "__main__":
    raise SystemExit(main())
