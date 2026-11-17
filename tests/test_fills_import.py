"""Uploading a fills export (.csv / .xlsx): preview, errors and the append-only import
(synthetic data only)."""

import datetime as dt
import io

import pandas as pd
import pytest
from openpyxl import Workbook

from trading_os import dashboard, fills_import, journal
from trading_os.config import load_config

CFG = load_config()
RULES = CFG.journal
A, B = ("".join([c, "Z", "Q", c]) for c in "AB")
HEADER = "trade_date,ticker,side,quantity,price,fees"
BODY = [
    f"2026-11-02,{A},Buy,100,10.50,1.0",
    f"2026-11-03,{A},Buy,100,11.00,1.0",
    f"2026-11-05,{A},Sell,200,12.00,2.0",
    f"2026-11-04,{B},Buy,10,5.00,0",
]


def csv_bytes(header=HEADER, rows=BODY) -> bytes:
    return "\n".join([header, *rows]).encode()


def test_preview_reports_rows_columns_new_fills_and_dates(tmp_path):
    seen = fills_import.preview(tmp_path, RULES, "fills.csv", csv_bytes())
    assert seen.ok and seen.rows == 4 and seen.sheet is None
    assert (seen.new, seen.existing) == (4, 0)
    assert (seen.first_date, seen.last_date) == (dt.date(2026, 11, 2), dt.date(2026, 11, 5))
    assert seen.missing == [] and set(seen.found) == set(RULES["csv_columns"])
    text = " ".join(fills_import.summary_lines(seen))
    assert A not in text and "4 new fills" in text  # no ticker list on the page


def test_import_is_append_only_and_a_second_upload_adds_nothing(tmp_path):
    first = fills_import.run_import(tmp_path, CFG, "fills.csv", csv_bytes())
    assert first.startswith("Journal: 4 new fills, 1 closed trades")
    fills_before = len(journal.load_fills(tmp_path))
    seen = fills_import.preview(tmp_path, RULES, "fills.csv", csv_bytes())
    assert (seen.new, seen.existing) == (0, 4)
    second = fills_import.run_import(tmp_path, CFG, "fills.csv", csv_bytes())
    assert second.startswith("Journal: 0 new fills")
    assert len(journal.load_fills(tmp_path)) == fills_before
    assert len(dashboard.latest_journal(tmp_path)) == 1


def test_a_later_export_adds_only_its_new_rows(tmp_path):
    fills_import.run_import(tmp_path, CFG, "a.csv", csv_bytes(rows=BODY[:2]))
    seen = fills_import.preview(tmp_path, RULES, "b.csv", csv_bytes())
    assert (seen.new, seen.existing) == (2, 2)


def test_headers_with_odd_case_spaces_and_a_bom_are_matched(tmp_path):
    header = " Trade_Date , TICKER,Side ,Quantity,PRICE, Fees"
    seen = fills_import.preview(tmp_path, RULES, "x.csv", csv_bytes(header))
    assert seen.ok and seen.new == 4
    bom = b"\xef\xbb\xbf" + csv_bytes()
    assert fills_import.preview(tmp_path, RULES, "x.csv", bom).ok


def test_semicolons_and_decimal_commas(tmp_path):
    rows = [
        f"2026-11-02;{A};Buy;100;10,50;1,5",
        f"2026-11-05;{A};Sell;100;1.012,25;1,5",
    ]
    text = ";".join(HEADER.split(",")) + "\n" + "\n".join(rows)
    seen = fills_import.preview(tmp_path, RULES, "x.csv", text.encode())
    assert seen.ok
    assert seen.fills.set_index("side")["price"].to_dict() == {"buy": 10.5, "sell": 1012.25}
    assert seen.fills["fees"].tolist() == [1.5, 1.5]


def test_a_title_above_the_header_row_is_skipped(tmp_path):
    text = "Account export\n\n" + "\n".join([HEADER, *BODY])
    seen = fills_import.preview(tmp_path, RULES, "x.csv", text.encode())
    assert seen.ok and seen.rows == 4


def test_missing_columns_are_listed_and_the_config_is_named(tmp_path):
    header = "trade_date,ticker,side,qty,price,fees"
    seen = fills_import.preview(tmp_path, RULES, "x.csv", csv_bytes(header))
    assert not seen.ok and seen.missing == ["quantity"]
    assert "quantity" in seen.error and "journal.csv_columns" in seen.error
    assert "qty" in seen.error  # what the file does have
    with pytest.raises(ValueError, match="journal.csv_columns"):
        fills_import.run_import(tmp_path, CFG, "x.csv", csv_bytes(header))
    assert journal.load_fills(tmp_path).empty  # nothing was written


def test_fees_column_is_optional(tmp_path):
    header = "trade_date,ticker,side,quantity,price"
    rows = [r.rsplit(",", 1)[0] for r in BODY]
    seen = fills_import.preview(tmp_path, RULES, "x.csv", csv_bytes(header, rows))
    assert seen.ok and (seen.fills["fees"] == 0).all() and "fees" not in seen.found


def test_bad_side_date_and_empty_file_give_readable_errors(tmp_path):
    bad_side = csv_bytes(rows=[f"2026-11-02,{A},Swap,1,1,0"])
    assert "unknown side values" in fills_import.preview(tmp_path, RULES, "x.csv", bad_side).error
    bad_date = csv_bytes(rows=[f"02/11/2026,{A},Buy,1,1,0"])
    assert "date_format" in fills_import.preview(tmp_path, RULES, "x.csv", bad_date).error
    empty = fills_import.preview(tmp_path, RULES, "x.csv", HEADER.encode())
    assert not empty.ok and "no fills" in empty.error
    assert not fills_import.preview(tmp_path, RULES, "x.csv", b"").ok
    assert "unsupported" in fills_import.preview(tmp_path, RULES, "x.pdf", b"%PDF").error
    assert not fills_import.preview(tmp_path, RULES, "x.xlsx", b"not a zip").ok


def xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_xlsx_picks_the_sheet_with_the_columns_and_reads_real_dates(tmp_path):
    header = HEADER.split(",")
    rows = [
        [dt.datetime(2026, 11, 2), A, "Buy", 100, 10.5, 1.0],
        [dt.datetime(2026, 11, 5), A, "Sell", 100, 12.0, 1.0],
    ]
    book = xlsx_bytes({"Summary": [["Report"], ["total", 2]], "Trades": [header, *rows]})
    seen = fills_import.preview(tmp_path, RULES, "export.xlsx", book)
    assert seen.ok and seen.sheet == "Trades" and seen.rows == 2
    assert (seen.first_date, seen.last_date) == (dt.date(2026, 11, 2), dt.date(2026, 11, 5))
    out = fills_import.run_import(tmp_path, CFG, "export.xlsx", book)
    assert out.startswith("Journal: 2 new fills, 1 closed trades")
    assert fills_import.preview(tmp_path, RULES, "export.xlsx", book).new == 0


def test_xlsx_with_text_dates_and_text_numbers(tmp_path):
    book = xlsx_bytes({"S": [HEADER.split(","), ["2026-11-02", A, "buy", "10", "5,25", ""]]})
    seen = fills_import.preview(tmp_path, RULES, "x.xlsx", book)
    assert seen.ok and seen.fills["price"].iloc[0] == 5.25 and seen.fills["fees"].iloc[0] == 0


def test_xlsx_without_the_columns_lists_what_it_has(tmp_path):
    book = xlsx_bytes({"S": [["a", "b"], [1, 2]]})
    seen = fills_import.preview(tmp_path, RULES, "x.xlsx", book)
    assert not seen.ok and "journal.csv_columns" in seen.error and seen.missing


def test_the_command_line_reader_is_tolerant_too(tmp_path):
    path = tmp_path / "f.csv"
    path.write_bytes(csv_bytes(" Trade_Date,Ticker,SIDE,Quantity,Price,Fees"))
    fills = journal.read_fills(path, RULES)
    assert len(fills) == 4 and list(fills.columns) == journal.FILL_COLUMNS
    assert pd.api.types.is_float_dtype(fills["price"])
