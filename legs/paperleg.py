"""Paper leg: per-bar direction calls on BTC and ETH, graded only by the Hyperliquid candle close.

    python paperleg.py tick                # resolve closed bars, then call the bar that just opened
    python paperleg.py board [--days 14]   # per leg, per UTC day: resolved count and loss rate
    python paperleg.py run --every 60      # loop tick
    python paperleg.py backtest --days 7   # separate ledger; never on the board
    python paperleg.py review [--date D]   # end-of-day: force-resolve, then print ONLY resolved count and loss rate per leg
    python paperleg.py review --pull       # the ledger lives on the VPS: copy it down (read-only there), then print the board

Rules are frozen in RULES.md. The only grader is the candle print from api.hyperliquid.xyz;
the leg never reads anything about the bar it is calling. One bit per call. Ties are losses.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CALLS = DATA / "calls.jsonl"
BACKTEST = DATA / "backtest.jsonl"
LOG = DATA / "tick.log"
LOCK = DATA / "lock"
BOARD_DIR = DATA / "board"

INFO_URL = "https://api.hyperliquid.xyz/info"
MARKETS = ("BTC", "ETH")
INTERVAL = "15m"
BAR_SECONDS = 900
CALL_WINDOW_SECONDS = 120  # a call made later than this into the bar has seen the bar; it is not made
LEGS = ("mom1", "rev1", "long")

# The ticker runs on the VPS (cron, every minute); the laptop only reviews. One writer, one ledger.
VPS_HOST = "root@207.148.31.200"
VPS_DATA = "/opt/papertrade/legs/data"
PULLED = ("calls.jsonl", "tick.log", "board.jsonl", "board")


# ----------------------------------------------------------------------------- rules (frozen; see RULES.md)

def rule(leg: str, prev: dict) -> str:
    """Direction for the bar that just opened, from the last CLOSED bar only."""
    up = float(prev["c"]) > float(prev["o"])
    down = float(prev["c"]) < float(prev["o"])
    if leg == "mom1":
        return "short" if down else "long"
    if leg == "rev1":
        return "long" if down else "short"
    if leg == "long":
        return "long"
    raise ValueError(leg)


def grade(direction: str, bar: dict) -> int:
    """1 = right, 0 = wrong. A tie is a loss: the operator's definition, not the leg's."""
    o, c = float(bar["o"]), float(bar["c"])
    if direction == "long":
        return int(c > o)
    return int(c < o)


# ----------------------------------------------------------------------------- hyperliquid prints

def info(payload: dict, attempts: int = 5) -> object:
    body = json.dumps(payload).encode()
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(INFO_URL, data=body, headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"hyperliquid info failed: {last}")


def candles(coin: str, start_ms: int, end_ms: int) -> list[dict]:
    out = info({"type": "candleSnapshot", "req": {"coin": coin, "interval": INTERVAL, "startTime": start_ms, "endTime": end_ms}})
    return sorted(out, key=lambda b: b["t"])


def mids() -> dict:
    return info({"type": "allMids"})


# ----------------------------------------------------------------------------- ledger

def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    DATA.mkdir(exist_ok=True)
    with path.open("a") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")


def rewrite(path: Path, rows: list[dict]) -> None:
    DATA.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    tmp.replace(path)


def call_id(leg: str, market: str, bar_start: int) -> str:
    return f"{leg}|{market}|{bar_start}"


def log(msg: str) -> None:
    DATA.mkdir(exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


# ----------------------------------------------------------------------------- single writer

@contextmanager
def ledger_lock(wait: int = 45):
    """One writer at a time: the minute tick and the daily review share calls.jsonl."""
    DATA.mkdir(exist_ok=True)
    deadline = time.time() + wait
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if LOCK.stat().st_mtime < time.time() - 300:  # stale: a crashed holder
                LOCK.unlink(missing_ok=True)
                continue
            if time.time() > deadline:
                raise RuntimeError("ledger lock held too long")
            time.sleep(0.5)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        LOCK.unlink(missing_ok=True)


# ----------------------------------------------------------------------------- tick

def tick(now: float | None = None) -> None:
    with ledger_lock():
        _tick(now)


def _tick(now: float | None = None) -> None:
    now = now or time.time()
    now_ms = int(now * 1000)
    rows = load(CALLS)
    known = {r["id"] for r in rows}
    changed = False

    # 1. resolve: every open call whose bar has closed, graded by the candle print
    open_by_market: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("result") is None and (r["bar_start"] + BAR_SECONDS) * 1000 <= now_ms:
            open_by_market.setdefault(r["market"], []).append(r)
    for market, pending in open_by_market.items():
        lo = min(r["bar_start"] for r in pending) * 1000
        bars = {b["t"]: b for b in candles(market, lo, now_ms)}
        for r in pending:
            bar = bars.get(r["bar_start"] * 1000)
            if bar is None or bar["T"] >= now_ms:
                continue
            r["result"] = grade(r["direction"], bar)
            r["o"], r["c"] = bar["o"], bar["c"]
            r["resolved_at"] = int(now)
            changed = True
    if changed:
        rewrite(CALLS, rows)
        n = sum(len(v) for v in open_by_market.values())
        log(f"resolved up to {n} calls")

    # 1b. daily review: the first tick after UTC midnight writes the board for the day that just ended
    yesterday = datetime.fromtimestamp(now - 86400, timezone.utc).strftime("%Y-%m-%d")
    if not (BOARD_DIR / f"{yesterday}.final").exists() and any(
        datetime.fromtimestamp(r["bar_start"], timezone.utc).strftime("%Y-%m-%d") == yesterday for r in rows
    ):
        text = _write_review(yesterday, rows, now)
        log("daily review written: " + text.replace(chr(10), " | "))

    # 2. call: the bar that just opened, only inside the call window, only from the last closed bar
    bar_start = int(now // BAR_SECONDS) * BAR_SECONDS
    into = now - bar_start
    if into > CALL_WINDOW_SECONDS:
        if into < CALL_WINDOW_SECONDS + 60 and not all(call_id(leg, m, bar_start) in known for leg in LEGS for m in MARKETS):
            log(f"MISSED bar {bar_start}: first tick was {into:.0f}s in, window is {CALL_WINDOW_SECONDS}s (infrastructure, not a signal)")
        return
    new: list[dict] = []
    mid = None
    try:
        mid = mids()
    except RuntimeError as exc:
        log(f"mids unavailable: {exc}")
    for market in MARKETS:
        if all(call_id(leg, market, bar_start) in known for leg in LEGS):
            continue
        prev_bars = [b for b in candles(market, (bar_start - 3 * BAR_SECONDS) * 1000, now_ms) if b["T"] < bar_start * 1000]
        if not prev_bars:
            log(f"{market}: no closed bar before {bar_start}")
            continue
        prev = prev_bars[-1]
        if prev["t"] != (bar_start - BAR_SECONDS) * 1000:
            log(f"{market}: last closed bar is {prev['t']}, not the one before {bar_start}; skipping")
            continue
        for leg in LEGS:
            cid = call_id(leg, market, bar_start)
            if cid in known:
                continue
            new.append({
                "id": cid, "leg": leg, "market": market, "bar_start": bar_start,
                "direction": rule(leg, prev), "made_at": int(now),
                "prev_o": prev["o"], "prev_c": prev["c"],
                "mid_at_call": (mid or {}).get(market),
                "result": None,
            })
    append(CALLS, new)
    if new:
        log(f"called {len(new)} for bar {bar_start}")


# ----------------------------------------------------------------------------- board

def board(days: int, as_json: bool = False) -> None:
    rows = load(CALLS)
    cutoff = time.time() - days * 86400
    table: dict[tuple[str, str], dict] = {}
    for r in rows:
        if r["bar_start"] < cutoff:
            continue
        day = datetime.fromtimestamp(r["bar_start"], timezone.utc).strftime("%Y-%m-%d")
        cell = table.setdefault((day, r["leg"]), {"resolved": 0, "losses": 0, "open": 0})
        if r["result"] is None:
            cell["open"] += 1
        else:
            cell["resolved"] += 1
            cell["losses"] += 1 - r["result"]
    totals: dict[str, dict] = {}
    for (_, leg), cell in table.items():
        t = totals.setdefault(leg, {"resolved": 0, "losses": 0})
        t["resolved"] += cell["resolved"]
        t["losses"] += cell["losses"]
    if as_json:
        print(json.dumps({"days": {f"{d}|{l}": c for (d, l), c in table.items()}, "totals": totals}, indent=1))
        return
    print(f"{'day':<11}{'leg':<6}{'resolved':>9}{'loss rate':>10}{'open':>6}")
    for (day, leg), cell in sorted(table.items()):
        rate = f"{cell['losses'] / cell['resolved']:.3f}" if cell["resolved"] else "-"
        print(f"{day:<11}{leg:<6}{cell['resolved']:>9}{rate:>10}{cell['open']:>6}")
    print("-" * 42)
    for leg, t in sorted(totals.items()):
        rate = f"{t['losses'] / t['resolved']:.3f}" if t["resolved"] else "-"
        print(f"{'total':<11}{leg:<6}{t['resolved']:>9}{rate:>10}")


# ----------------------------------------------------------------------------- review (the daily skip-level)

def pull_ledger() -> tuple[bool, str]:
    """Copy the ledger, the machine log and the board record down from the VPS. Read-only there: scp only reads.
    Returns (ok, why not)."""
    import subprocess
    DATA.mkdir(exist_ok=True)
    srcs = [f"{VPS_HOST}:{VPS_DATA}/{name}" for name in PULLED]
    r = subprocess.run(["scp", "-q", "-p", "-r", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", *srcs, str(DATA) + os.sep],
                       capture_output=True, text=True)
    err = (r.stderr or "").strip().splitlines()
    return r.returncode == 0, (err[-1] if err else f"scp exit {r.returncode}")


def review(date: str | None, now: float | None = None, pull: bool = False) -> None:
    """Force-resolve every closed bar, then print the two numbers per leg for one UTC day. Nothing else is printed
    above the line. Below the line: infrastructure faults only (unresolved closed bars, missed bars), never scored.

    With `pull`, the ticker on the VPS is the only writer: the ledger is copied down first and the review is
    rendered from it without ticking or writing here. A failed pull is a fault line over the stale local copy."""
    now = now or time.time()
    if date is None:  # within two hours after UTC midnight, the day under review is the one that just ended
        date = datetime.fromtimestamp(now - 2 * 3600, timezone.utc).strftime("%Y-%m-%d")
    if pull:
        ok, why = pull_ledger()
        text, *_ = _render_review(date, load(CALLS), now)
        if not ok:
            text += chr(10) + f"FAULT: ledger pull from {VPS_HOST} failed ({why}); numbers are the stale local copy"
        print(text)
        return
    tick(now)  # resolve pass (and the current bar's call if inside the window)
    print(_write_review(date, load(CALLS), now))


def _render_review(date: str, all_rows: list[dict], now: float) -> tuple[str, dict, int, list[str], bool]:
    rows = [r for r in all_rows if datetime.fromtimestamp(r["bar_start"], timezone.utc).strftime("%Y-%m-%d") == date]
    per_leg: dict[str, dict] = {leg: {"resolved": 0, "losses": 0} for leg in LEGS}
    unresolved_closed, open_live = [], 0
    for r in rows:
        if r["result"] is None:
            if (r["bar_start"] + BAR_SECONDS) <= now:
                unresolved_closed.append(r["id"])
            else:
                open_live += 1
            continue
        per_leg[r["leg"]]["resolved"] += 1
        per_leg[r["leg"]]["losses"] += 1 - r["result"]
    day_start = int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    first_call = min((r["bar_start"] for r in rows), default=None)
    closed_bars_today = max(0, min(int(now), day_start + 86400) - max(day_start, first_call or day_start)) // BAR_SECONDS
    called_bars = len({r["bar_start"] for r in rows})
    lines = [f"BOARD {date} (UTC)", f"{'leg':<6}{'resolved':>9}{'loss rate':>10}"]
    for leg in LEGS:
        c = per_leg[leg]
        rate = f"{c['losses'] / c['resolved']:.3f}" if c["resolved"] else "-"
        lines.append(f"{leg:<6}{c['resolved']:>9}{rate:>10}")
    distinct = sum(c["resolved"] for c in per_leg.values())
    lines.append(f"distinct resolved calls: {distinct}")
    lines.append("-" * 30)
    faults = []
    if unresolved_closed:
        faults.append(f"FAULT: {len(unresolved_closed)} calls on closed bars still unresolved (grader unreachable?)")
    if first_call is not None and called_bars < closed_bars_today:
        faults.append(f"FAULT: {closed_bars_today - called_bars} bars since the first call had no call (ticker down or late)")
    lines.append(chr(10).join(faults) if faults else f"no infrastructure faults; {open_live} calls on the live bar still open")
    final = now >= day_start + 86400
    lines.append(("FINAL" if final else "PROVISIONAL (day not over)") + f" review at {datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='minutes')}")
    return chr(10).join(lines), per_leg, distinct, faults, final


def _write_review(date: str, all_rows: list[dict], now: float) -> str:
    text, per_leg, distinct, faults, final = _render_review(date, all_rows, now)
    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    (BOARD_DIR / f"{date}.txt").write_text(text + chr(10))
    if final:
        (BOARD_DIR / f"{date}.final").write_text(str(int(now)))
    with (DATA / "board.jsonl").open("a") as fh:
        fh.write(json.dumps({"date": date, "reviewed_at": int(now), "legs": per_leg, "distinct": distinct, "faults": faults, "final": final}) + chr(10))
    return text


# ----------------------------------------------------------------------------- backtest (separate ledger)

def backtest(days: int) -> None:
    """Runs the frozen rules over past candles. Lands in backtest.jsonl, which the board never reads."""
    end = int(time.time() // BAR_SECONDS) * BAR_SECONDS
    start = end - days * 86400
    out: list[dict] = []
    for market in MARKETS:
        bars = candles(market, start * 1000, end * 1000)
        bars = [b for b in bars if b["T"] < end * 1000]
        for prev, bar in zip(bars, bars[1:]):
            if bar["t"] - prev["t"] != BAR_SECONDS * 1000:
                continue
            for leg in LEGS:
                d = rule(leg, prev)
                out.append({"leg": leg, "market": market, "bar_start": bar["t"] // 1000, "direction": d, "result": grade(d, bar), "ledger": "backtest"})
    rewrite(BACKTEST, out)
    print(f"backtest: {len(out)} calls over {days} days -> {BACKTEST} (not on the board)")
    for leg in LEGS:
        rs = [r["result"] for r in out if r["leg"] == leg]
        print(f"  {leg:<5} n={len(rs):<5} loss rate={1 - sum(rs) / len(rs):.3f}" if rs else f"  {leg}: none")


# ----------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick")
    b = sub.add_parser("board")
    b.add_argument("--days", type=int, default=14)
    b.add_argument("--json", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--every", type=int, default=60)
    t = sub.add_parser("backtest")
    t.add_argument("--days", type=int, default=7)
    v = sub.add_parser("review")
    v.add_argument("--date", default=None, help="UTC day, YYYY-MM-DD; default: today, or yesterday within 2h after midnight UTC")
    v.add_argument("--pull", action="store_true", help=f"copy the ledger down from {VPS_HOST} first; no local tick, no local write")
    a = p.parse_args(argv)
    if a.cmd == "tick":
        tick()
    elif a.cmd == "board":
        board(a.days, a.json)
    elif a.cmd == "backtest":
        backtest(a.days)
    elif a.cmd == "review":
        review(a.date, pull=a.pull)
    elif a.cmd == "run":
        while True:
            try:
                tick()
            except Exception as exc:  # noqa: BLE001
                log(f"tick failed: {exc}")
            time.sleep(a.every)


if __name__ == "__main__":
    main()
