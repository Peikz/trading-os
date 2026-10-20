"""`python -m trading_os.sec_bulk_cli --mode build ...` (the SEC bulk job's entry)."""

from trading_os.sec_bulk import main

if __name__ == "__main__":
    raise SystemExit(main())
