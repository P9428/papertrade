"""Calibration ledger: the live twin of the paper baseline, at the venue's minimum size, one fill per bar.

    python legs/calib.py run 0xWALLET --fills 10 [--live]   # follow mom1's call on the next N bars, one $10 position at a time
    python legs/calib.py settle 0xWALLET [--live]           # finish any fill left open (close at bar end, then grade)
    python legs/calib.py hurdle                             # the measured numbers; the operator writes the hurdle into RULES.md

This is NOT the board and NOT the live leg of RULES.md. It is step 3 of LIVE-LEG.md: a separate ledger
(legs/data/calib.jsonl) whose only job is to measure what the paper book cannot: fill delay, entry slip against the
paper mid, the fraction of a winning move the venue pays out, what a losing move costs, PAPER minted, and the
paper-to-live loss-rate gap on identical bars. Every number here is read from the account balance and the chain
print; nothing is modeled.

Dry-run by default. Without --live it sends nothing, grades the paper side only and marks the row "dry".
"""

from __future__ import annotations

import argparse
import time

import liveleg
import paperleg

CALIB = paperleg.DATA / "calib.jsonl"
BASELINE = "mom1"           # the live twin follows the baseline's call; RULES.md names the baseline
MAX_FILLS_PER_RUN = 10      # LIVE-LEG.md step 3; the operator raises it, not the machine
POLL = 10                   # seconds between account snapshots
TWIN_WAIT = 90              # seconds to wait for the paper tick to write the bar's call


# ----------------------------------------------------------------------------- helpers

def wad(x) -> float:
    return int(x) / liveleg.WAD


def bar_of(ts: float) -> int:
    return int(ts) // paperleg.BAR_SECONDS * paperleg.BAR_SECONDS


def twin(bar_start: int, market: str, rows: list[dict] | None = None) -> dict | None:
    """The paper baseline's call for this bar, or None if the tick has not written it yet."""
    rows = paperleg.load(paperleg.CALLS) if rows is None else rows
    want = paperleg.call_id(BASELINE, market, bar_start)
    return next((r for r in rows if r["id"] == want), None)


def wait_for_twin(bar_start: int, market: str) -> dict:
    deadline = time.time() + TWIN_WAIT
    while time.time() < deadline:
        t = twin(bar_start, market)
        if t:
            return t
        time.sleep(5)
    raise RuntimeError(f"paper {BASELINE} made no call for {market} bar {bar_start}; the twin follows the paper call or does nothing")


def money(snap: dict) -> dict:
    """What the venue says the account holds. Winners can land in `queued` when the pool is short, so both count."""
    p = snap.get("paper") or {}
    return {"balance": int(snap.get("balance", 0)), "queued": int(snap.get("queued", 0)),
            "paper": int(p.get("balance", 0)) + int(p.get("staked", 0))}


def find_position(snap: dict, inst: int, is_long: bool) -> list | None:
    for pos in snap.get("openPositions") or []:
        if int(pos[1]) == inst and bool(pos[2]) == is_long:
            return pos
    return None


def grade_row(row: dict, bar: dict, before: dict, after: dict) -> dict:
    """Pure: turn balances before and after plus the bar's print into the measured numbers."""
    o, c = float(bar["o"]), float(bar["c"])
    notional = row["margin_usd"] * row["leverage"]
    raw_move_usd = abs(c - o) / o * notional
    net_usd = (after["balance"] + after["queued"] - before["balance"] - before["queued"]) / liveleg.WAD
    out = {
        "bar_o": bar["o"], "bar_c": bar["c"],
        "paper_bit": paperleg.grade(row["side"], bar),
        "live_bit": int(net_usd > 0),
        "net_usd": round(net_usd, 6),
        "raw_move_usd": round(raw_move_usd, 6),
        "paper_minted": round((after["paper"] - before["paper"]) / liveleg.WAD, 3),
    }
    if raw_move_usd > 0:
        ratio = net_usd / raw_move_usd
        out["kept"] = round(ratio, 4) if net_usd > 0 else None
        out["loss_ratio"] = round(-ratio, 4) if net_usd <= 0 else None
    return out


# ----------------------------------------------------------------------------- one fill

def open_twin(wallet: str, market: str, live: bool, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    bar_start = bar_of(now)
    if now - bar_start > paperleg.CALL_WINDOW_SECONDS:
        raise RuntimeError("past the call window for this bar; wait for the next bar")
    t = wait_for_twin(bar_start, market)
    state = liveleg.trading_state()
    margin, lev = liveleg.minimum_unit(state)
    inst = liveleg.INSTRUMENTS[market]
    liveleg.check_open(state, inst, lev)
    before = money(liveleg.account_snapshot(wallet)) if live else {"balance": 0, "queued": 0, "paper": 0}
    mid = paperleg.mids().get(market)
    s = liveleg.session_key()
    msg = {"user": wallet.lower(), "instrumentId": inst, "isLong": t["direction"] == "long", "size": margin, "leverage": lev,
           "useDebt": False, "nonce": liveleg.next_nonce(wallet), "deadline": int(time.time()) + liveleg.INTENT_TTL}
    prepared = liveleg.sign_intent("OpenPosition", msg, s["privateKey"])
    row = {
        "id": f"calib|{market}|{bar_start}", "bar_start": bar_start, "market": market, "side": t["direction"],
        "twin": t["id"], "mid_at_call": t.get("mid_at_call"), "hl_mid_at_send": mid,
        "margin_usd": wad(margin), "leverage": lev, "off_hours": state.get("offHours"),
        "open_sent_at": int(time.time()), "open_intent": prepared["intentId"], "before": before,
        "status": "open-sent" if live else "dry",
    }
    liveleg.send(prepared, live, f"calib-open:{market}:{t['direction']}")
    paperleg.append(CALIB, [row])
    return row


def settle_row(wallet: str, row: dict, live: bool) -> dict:
    """Wait for the fill, close at bar end, wait for the close, grade from balances and the bar's print."""
    inst = liveleg.INSTRUMENTS[row["market"]]
    is_long = row["side"] == "long"
    bar_end = row["bar_start"] + paperleg.BAR_SECONDS
    if live and row["status"] == "open-sent":
        while time.time() < bar_end - 30:
            pos = find_position(liveleg.account_snapshot(wallet), inst, is_long)
            if pos:
                row.update({"position_id": int(pos[0]), "filled_at": int(time.time()), "entry_raw": str(pos[4]), "bust_raw": str(pos[7]),
                            "fill_delay_s": int(time.time()) - row["open_sent_at"], "status": "filled"})
                break
            time.sleep(POLL)
        if row["status"] == "open-sent":
            row["status"] = "unfilled"
            return row
    time.sleep(max(0.0, bar_end - time.time()))
    if live and row["status"] in ("filled", "close-sent"):
        snap = liveleg.account_snapshot(wallet)
        if find_position(snap, inst, is_long) is None and row["status"] == "filled":
            row["status"] = "liquidated"      # gone before we closed it: a loss like any other
        elif row["status"] == "filled":
            s = liveleg.session_key()
            msg = {"user": wallet.lower(), "positionIds": [row["position_id"]], "nonce": liveleg.next_nonce(wallet),
                   "deadline": int(time.time()) + liveleg.INTENT_TTL}
            prepared = liveleg.sign_intent("Close", msg, s["privateKey"])
            liveleg.send(prepared, True, f"calib-close:{row['position_id']}")
            row.update({"close_sent_at": int(time.time()), "close_intent": prepared["intentId"], "status": "close-sent"})
        deadline = time.time() + 600
        while row["status"] == "close-sent" and time.time() < deadline:
            snap = liveleg.account_snapshot(wallet)
            if find_position(snap, inst, is_long) is None:
                row["status"] = "closed"
            else:
                time.sleep(POLL)
        if row["status"] == "close-sent":
            return row                              # still open; `settle` again later
        row["after"] = money(snap)
    bars = paperleg.candles(row["market"], row["bar_start"] * 1000, bar_end * 1000)
    bar = next((b for b in bars if int(b["t"]) == row["bar_start"] * 1000), None)
    if not bar:
        return row
    if live and row["status"] in ("closed", "liquidated"):
        row.update(grade_row(row, bar, row["before"], row["after"]))
        row["status"] = "settled"
    else:
        row.update({"bar_o": bar["o"], "bar_c": bar["c"], "paper_bit": paperleg.grade(row["side"], bar)})
    return row


def upsert(row: dict) -> None:
    rows = paperleg.load(CALIB)
    if any(r["id"] == row["id"] for r in rows):
        rows = [row if r["id"] == row["id"] else r for r in rows]
    else:
        rows.append(row)
    paperleg.rewrite(CALIB, rows)


# ----------------------------------------------------------------------------- commands

def cmd_run(a: argparse.Namespace) -> None:
    fills = min(a.fills, MAX_FILLS_PER_RUN)
    markets = [m.upper() for m in a.markets]
    done = 0
    while done < fills:
        now = time.time()
        nxt = bar_of(now) + paperleg.BAR_SECONDS
        print(f"waiting {nxt - now:.0f}s for bar {nxt} ({done}/{fills} fills settled)")
        time.sleep(max(0.0, nxt - now + 3))
        market = markets[done % len(markets)]
        try:
            row = open_twin(a.wallet, market, a.live)
        except RuntimeError as exc:
            print(f"skip bar: {exc}")
            continue
        row = settle_row(a.wallet, row, a.live)
        upsert(row)
        print(f"{row['id']} {row['side']} -> {row['status']}  paper_bit={row.get('paper_bit')} live_bit={row.get('live_bit')} "
              f"net_usd={row.get('net_usd')} kept={row.get('kept')}")
        if row["status"] in ("settled", "dry", "unfilled"):
            done += 1
        if row["status"] == "liquidated":
            print("a position was liquidated before close; stopping this run (the operator restarts it)")
            return
        if row["status"] in ("close-sent", "open-sent"):
            print("fill not resolved; stopping. Run `calib.py settle` once the batch executes")
            return


def cmd_settle(a: argparse.Namespace) -> None:
    for row in paperleg.load(CALIB):
        if row["status"] in ("open-sent", "filled", "close-sent") or (row["status"] == "dry" and "paper_bit" not in row):
            row = settle_row(a.wallet, row, a.live)
            upsert(row)
            print(f"{row['id']} -> {row['status']}")


def hurdle_report(rows: list[dict]) -> str:
    settled = [r for r in rows if r.get("status") == "settled"]
    dry = [r for r in rows if r.get("status") == "dry" and "paper_bit" in r]
    lines = [f"calibration ledger: {len(settled)} settled live fills, {len(dry)} dry rows, {len(rows) - len(settled) - len(dry)} other"]
    if not settled:
        lines.append("no live fill yet: the hurdle in RULES.md (0.43) is still the published-curve estimate, not a measurement")
        return "\n".join(lines)
    n = len(settled)
    live_lr = sum(1 - r["live_bit"] for r in settled) / n
    paper_lr = sum(1 - r["paper_bit"] for r in settled) / n
    kept = [r["kept"] for r in settled if r.get("kept") is not None]
    lost = [r["loss_ratio"] for r in settled if r.get("loss_ratio") is not None]
    delays = [r["fill_delay_s"] for r in settled if "fill_delay_s" in r]
    lines.append(f"live loss rate {live_lr:.3f}  paper loss rate on the same bars {paper_lr:.3f}  gap {live_lr - paper_lr:+.3f} "
                 f"(RULES.md stops a live leg above +0.10 over a batch)")
    lines.append(f"net USD {sum(r['net_usd'] for r in settled):+.4f}  PAPER minted {sum(r['paper_minted'] for r in settled):,.1f}")
    if delays:
        lines.append(f"fill delay s: mean {sum(delays) / len(delays):.0f}  max {max(delays)}")
    if kept and lost:
        k, l = sum(kept) / len(kept), sum(lost) / len(lost)
        lines.append(f"kept (winners) mean {k:.3f} over {len(kept)}  loss ratio (losers) mean {l:.3f} over {len(lost)}")
        lines.append(f"MEASURED BREAKEVEN LOSS RATE kept/(kept+loss_ratio) = {k / (k + l):.3f}   (RULES.md carries 0.43 from the published curve)")
        lines.append("the operator writes the measured number into legs/RULES.md; this tool never does")
    else:
        lines.append("need at least one winner and one loser to measure both sides of the haircut")
    return "\n".join(lines)


def cmd_hurdle(_: argparse.Namespace) -> None:
    print(hurdle_report(paperleg.load(CALIB)))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("run"); x.add_argument("wallet"); x.add_argument("--fills", type=int, default=1)
    x.add_argument("--markets", nargs="+", default=["BTC"], choices=["BTC", "ETH", "btc", "eth"]); x.add_argument("--live", action="store_true")
    x.set_defaults(fn=cmd_run)
    x = sub.add_parser("settle"); x.add_argument("wallet"); x.add_argument("--live", action="store_true"); x.set_defaults(fn=cmd_settle)
    sub.add_parser("hurdle").set_defaults(fn=cmd_hurdle)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
