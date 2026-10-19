"""`python -m trading_os.alpaca_cli --ep-minutes ...` (the Alpaca jobs' entry point)."""

from trading_os.alpaca import main

if __name__ == "__main__":
    raise SystemExit(main())
