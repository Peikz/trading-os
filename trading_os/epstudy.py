"""Breakout Log rows in the EPStudyDatabase Google Sheet (SPEC §9, Phase 3).

Off until config `epstudy.enabled` is true, `sheet_id` is set and the secret
GOOGLE_SERVICE_ACCOUNT_JSON holds a service-account key with edit access to the sheet.
Each run reads the sheet's signal_id column once and appends only rows it doesn't have, so
re-runs never duplicate. The column list is config (match it to the sheet's header row).
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

import pandas as pd

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
API = "https://sheets.googleapis.com/v4/spreadsheets"


def session_from_secret(secret_json: str):
    """An authorized HTTP session from the service-account key (JSON text)."""
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    info = json.loads(secret_json)
    credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return AuthorizedSession(credentials)


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def to_cell(value: Any) -> Any:
    """Plain JSON values for the Sheets API."""
    if value is None or (not isinstance(value, str | bool) and pd.isna(value)):
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, dt.date | pd.Timestamp):
        return value.isoformat()[:10]
    if isinstance(value, float):
        return round(value, 4)
    if hasattr(value, "item"):  # numpy scalars
        return to_cell(value.item())
    return value


def rows_for(
    candidates: pd.DataFrame,
    scans: Iterable[str],
    columns: list[str],
) -> list[list[Any]]:
    """One row per hit of the configured scans, values taken from the stored candidates."""
    wanted = candidates[candidates["scan"].isin(list(scans))]
    rows = []
    for record in wanted.to_dict("records"):
        rows.append([to_cell(record.get(column)) for column in columns])
    return rows


def append_new(
    http, sheet_id: str, worksheet: str, columns: list[str], rows: list[list[Any]]
) -> int:
    """Append rows whose signal_id isn't in the sheet yet. Returns how many were added."""
    if not rows:
        return 0
    id_index = columns.index("signal_id")
    letter = _column_letter(id_index)
    sheet = quote(worksheet, safe="")
    response = http.get(f"{API}/{sheet_id}/values/{sheet}!{letter}:{letter}")
    response.raise_for_status()
    existing = {r[0] for r in response.json().get("values", []) if r}
    new = [row for row in rows if row[id_index] not in existing]
    if not new:
        return 0
    response = http.post(
        f"{API}/{sheet_id}/values/{sheet}!A1:append",
        params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
        json={"values": new},
    )
    response.raise_for_status()
    return len(new)
