"""Weekly job (SPEC §3: Sunday 18:00 Copenhagen). Reports the week's last session.

uv run python scripts/weekly.py --data-dir ../trading-os-data             # scheduled
uv run python scripts/weekly.py --data-dir ../trading-os-data --force --no-push   # manual
"""

from trading_os.job import main

if __name__ == "__main__":
    raise SystemExit(main("weekly", "Weekly", __doc__.splitlines()[0]))
