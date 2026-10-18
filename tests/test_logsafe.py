from trading_os.logsafe import redacted_traceback, run_guarded

# Built at runtime so the traceback's source lines can't contain the values themselves,
# exactly like real data flowing through the job.
TICKER = "".join(["ZZ", "ZQ"])
PRICE = 12 + 0.34


def failing():
    raise ValueError(f"ticker {TICKER} at ${PRICE}")


def test_failure_keeps_ticker_out_of_public_output(tmp_path, capsys):
    code = run_guarded(failing, tmp_path, "eod")
    out, err = capsys.readouterr()
    assert code == 1
    assert "ZZZQ" not in out + err and "12.34" not in out + err
    assert "ValueError" in out and "ValueError" in err
    log = next(tmp_path.glob("*_eod.log")).read_text(encoding="utf-8")
    assert "ZZZQ" in log  # the private copy keeps the full message


def test_success_passes_return_code(capsys):
    assert run_guarded(lambda: 0, None, "eod") == 0
    assert capsys.readouterr().out == ""


def test_redacted_traceback_has_frames_not_message():
    try:
        failing()
    except ValueError as exc:
        text = redacted_traceback(exc)
    assert "failing" in text and text.endswith("ValueError")
    assert "ZZZQ" not in text
