"""Offline checks for the calibration ledger: the twin lookup, the grading arithmetic and the hurdle report."""
import calib
import liveleg

WAD = liveleg.WAD


def test_twin_follows_the_baseline_call_on_the_same_bar():
    rows = [
        {"id": "mom1|BTC|1794189600", "leg": "mom1", "market": "BTC", "bar_start": 1794189600, "direction": "short", "mid_at_call": "101000"},
        {"id": "rev1|BTC|1794189600", "leg": "rev1", "market": "BTC", "bar_start": 1794189600, "direction": "long", "mid_at_call": "101000"},
    ]
    t = calib.twin(1794189600, "BTC", rows)
    assert t["id"] == "mom1|BTC|1794189600" and t["direction"] == "short"
    assert calib.twin(1794190500, "BTC", rows) is None
    assert calib.bar_of(1794189600 + 899) == 1794189600


def test_winner_kept_fraction_from_balances():
    row = {"side": "long", "margin_usd": 10.0, "leverage": 50}
    bar = {"o": "100000", "c": "100100"}            # +0.1% on $500 notional = $0.50 raw
    before = {"balance": 20 * WAD, "queued": 0, "paper": 0}
    after = {"balance": 20 * WAD + int(0.37 * WAD), "queued": 0, "paper": 0}
    g = calib.grade_row(row, bar, before, after)
    assert g["paper_bit"] == 1 and g["live_bit"] == 1
    assert abs(g["raw_move_usd"] - 0.5) < 1e-9
    assert abs(g["kept"] - 0.74) < 1e-6 and g["loss_ratio"] is None


def test_loser_pays_full_move_and_mints_paper():
    row = {"side": "long", "margin_usd": 10.0, "leverage": 50}
    bar = {"o": "100000", "c": "99900"}
    before = {"balance": 20 * WAD, "queued": 0, "paper": 0}
    after = {"balance": 20 * WAD - int(0.51 * WAD), "queued": 0, "paper": 48 * WAD}
    g = calib.grade_row(row, bar, before, after)
    assert g["paper_bit"] == 0 and g["live_bit"] == 0
    assert abs(g["loss_ratio"] - 1.02) < 1e-6 and g["kept"] is None
    assert g["paper_minted"] == 48.0


def test_paper_right_but_live_wrong_is_the_gap():
    """Direction right against the Hyperliquid close, but the venue's mark and delay ate it: live loss, paper win."""
    row = {"side": "short", "margin_usd": 10.0, "leverage": 50}
    bar = {"o": "100000", "c": "99990"}
    before = {"balance": 20 * WAD, "queued": 0, "paper": 0}
    after = {"balance": 20 * WAD - int(0.02 * WAD), "queued": 0, "paper": 2 * WAD}
    g = calib.grade_row(row, bar, before, after)
    assert g["paper_bit"] == 1 and g["live_bit"] == 0


def test_hurdle_report_measures_breakeven_from_both_sides():
    rows = [
        {"status": "settled", "live_bit": 1, "paper_bit": 1, "kept": 0.74, "loss_ratio": None, "net_usd": 0.37, "paper_minted": 0, "fill_delay_s": 20},
        {"status": "settled", "live_bit": 0, "paper_bit": 0, "kept": None, "loss_ratio": 1.0, "net_usd": -0.5, "paper_minted": 48, "fill_delay_s": 30},
        {"status": "settled", "live_bit": 0, "paper_bit": 1, "kept": None, "loss_ratio": 1.0, "net_usd": -0.1, "paper_minted": 9, "fill_delay_s": 40},
        {"status": "dry", "paper_bit": 1},
    ]
    out = calib.hurdle_report(rows)
    assert "3 settled live fills, 1 dry rows" in out
    assert "live loss rate 0.667  paper loss rate on the same bars 0.333  gap +0.333" in out
    assert "MEASURED BREAKEVEN LOSS RATE kept/(kept+loss_ratio) = 0.425" in out
    assert "operator writes" in out


def test_hurdle_report_without_fills_says_so():
    out = calib.hurdle_report([])
    assert "no live fill yet" in out and "0.43" in out
