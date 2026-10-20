"""SEC bulk fundamentals: parsing and point-in-time joins on tiny hand-made fixtures."""

import datetime as dt

from trading_os import sec_bulk


def test_header_acceptance_reads_the_eastern_wall_time():
    text = "<SEC-HEADER>&lt;ACCEPTANCE-DATETIME&gt;20250731163039\nACCESSION NUMBER: x"
    assert sec_bulk.header_acceptance(text) == dt.datetime(2025, 7, 31, 16, 30, 39)
    assert sec_bulk.header_acceptance("<ACCEPTANCE-DATETIME>20250102070001") == dt.datetime(
        2025, 1, 2, 7, 0, 1
    )
    assert sec_bulk.header_acceptance("nothing here") is None


def test_offset_class_names_the_three_conventions():
    header = dt.datetime(2025, 7, 31, 16, 30, 39)  # EDT, UTC-4
    assert sec_bulk.offset_class("2025-07-31T20:30:39.000Z", header) == "utc"
    assert sec_bulk.offset_class("2025-08-01T00:30:39.000Z", header) == "plus_offset"
    assert sec_bulk.offset_class("2025-07-31T16:30:39.000Z", header) == "et_wall"
    winter = dt.datetime(2025, 2, 3, 7, 0, 0)  # EST, UTC-5
    assert sec_bulk.offset_class("2025-02-03T12:00:00.000Z", winter) == "utc"
    assert sec_bulk.offset_class("2025-02-03T17:00:00.000Z", winter) == "plus_offset"
    assert sec_bulk.offset_class("2025-02-03T09:00:00.000Z", winter) == "other"
