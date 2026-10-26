from trading_os import ticket

ROW = {"ticker": "AAA", "scan": "ep_am", "grade": "A+", "grade_entry_rule": "t_1030",
       "plan_entry": 20.0, "plan_stop": 18.0}  # fmt: skip


def test_default_type_follows_the_plan():
    assert ticket.default_type(ROW) == "market"
    assert ticket.default_type({**ROW, "grade_entry_rule": "ah_1645"}) == "limit_ext"
    assert ticket.default_type({"scan": "ma_surf", "grade_entry_rule": "pivot_1000"}) == "stop"
    assert ticket.default_type({**ROW, "grade_entry_rule": "close"}) == "moc"


def test_market_ticket_sizes_on_the_risk_and_lists_the_stop_loss():
    t = ticket.build(ROW, "market", risk_usd=500, account_usd=100_000, max_position_pct=25)
    assert t.shares == 250 and t.risk_usd == 500 and not t.capped
    lines = dict(t.lines())
    assert lines["Order type"] == "Market" and lines["Stop loss (own order, GTC)"] == "18.00"
    assert "Limit price" not in lines and t.when.startswith("~10:30")


def test_stop_limit_sizes_on_the_limit_so_the_risk_holds():
    t = ticket.build({**ROW, "pivot": 21.0}, "stop_limit", 500, 100_000, 25)
    assert t.trigger == 21.0 and t.limit == 21.1
    assert t.shares == 161  # 500 / (21.10 - 18.00)


def test_own_limit_price_and_the_position_cap():
    t = ticket.build(ROW, "limit", 500, 10_000, 25, price=19.0)
    assert t.limit == 19.0 and t.capped and t.shares == 131  # 25 % of 10,000 / 19
    assert ticket.build(ROW, "limit", 500, 100_000, 25, price=17.5) is None  # under the stop
    assert ticket.build({"ticker": "X"}, "market", 500, 100_000, 25) is None
