"""DataFrame rows to JSON-safe values: NaN and NaT become null, dates ISO strings, numpy
scalars plain Python."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import numpy as np
import pandas as pd


def scalar(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.isoformat()
    if isinstance(v, dt.datetime | dt.date):
        return v.isoformat()
    if v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, np.ndarray | list | tuple):
        return [scalar(x) for x in v]
    if isinstance(v, bool | int | str):
        return v
    if isinstance(v, dict):
        return {str(k): scalar(x) for k, x in v.items()}
    return str(v)


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(k): scalar(v) for k, v in row.items()} for row in frame.to_dict("records")]
