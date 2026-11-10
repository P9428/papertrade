# legs

The 100-calls-a-day machine. Paper leg first; the live leg on papertrade runs beside it on the same bars once a rule clears burn-in (RULES.md).

## Paper leg

```
python legs/paperleg.py tick            # resolve closed bars, call the bar that just opened (idempotent; safe every minute)
python legs/paperleg.py board           # per leg, per UTC day: resolved count, loss rate, open calls
python legs/paperleg.py run --every 60  # loop
python legs/paperleg.py backtest --days 7   # separate ledger, never on the board
python legs/paperleg.py review          # the daily skip-level: force-resolve, then the two numbers per leg, nothing else
```

## The daily review

The review is the command `/board` in Claude Code (`~/.claude/commands/board.md`). It runs
`python legs/paperleg.py review` and shows the board verbatim, nothing else: resolved count and loss rate per leg,
then a line of infrastructure faults (closed bars left unresolved, bars with no call). Faults are fixed, never scored.
`/board 2026-11-07` reviews a given UTC day. No commentary, no backtest numbers, no rule changes come out of it; the only
decisions it can trigger are the kill and promotion rules already written in `RULES.md`.

The first minute tick after 00:00 UTC writes the final board for the day that just ended and marks it `.final`.
A review run during the day is marked PROVISIONAL and does not block the final one. `legs/data/board.jsonl` is the
append-only record of every review.

## Where the ticker runs

The laptop lost power at 2026-11-09 03:31Z and was dark for 21 hours: 81 bars without a call, a 90-call day. A box that
loses power cannot carry the machine. The ticker belongs on the VPS (`root@207.148.31.200`, the box that already carries
the hyperliquid leg); the laptop only reviews. One writer, one ledger.

Move it once, from Git Bash on the laptop (the operator's hand; the Claude Code classifier refuses remote writes):

```
bash legs/deploy_vps.sh
```

The script copies the code and the ledger up, installs a per-minute cron entry, runs one tick there against the grader,
disables the laptop's task, and switches `/board` to `python legs/paperleg.py review --pull`. From then on the review
copies `calls.jsonl`, `tick.log`, `board.jsonl` and `board/` down with scp (read-only on the VPS) and prints the board
from that copy, without ticking or writing here. A failed pull is a fault line over the stale local copy.

Until the move, the laptop's task `papertrade-paperleg` is the ticker: every minute, on battery, wakes the machine,
catches up missed runs, never overlaps itself, exit 0 since 2026-11-07. Re-create it if it is ever gone:

```
schtasks /Create /F /SC MINUTE /MO 1 /TN papertrade-paperleg /TR "\"C:\Program Files\Python312\pythonw.exe\" \"C:\Users\newce\papertrade\legs\paperleg.py\" tick"
```

- Markets BTC and ETH, 15-minute bars, three frozen rules: `mom1` (baseline), `rev1`, `long`. 576 calls a day, 192 per leg.
- Calls are made in the first 120 s of a bar from the last closed bar only. Later ticks skip the bar and log it; the leg never sees the bar it calls.
- The grader is the Hyperliquid `candleSnapshot` print for the bar, read after the bar's end. Long is right if close > open, short if close < open, tie is a loss.
- `data/calls.jsonl` is the board ledger (forward only). `data/backtest.jsonl` is the replay ledger. `data/tick.log` is the machine log. None of these are committed.
- Each call also records `mid_at_call` (Hyperliquid mid when the call was made), which is the live leg's entry reference for the paper-to-live gap.

## Live leg

Not running. See `../LIVE-LEG.md` for the three gates and their status.

## Calibration ledger (not the board, not the live leg)

```
python legs/calib.py run 0xWALLET --fills 10 --markets BTC ETH [--live]   # live twin of mom1 at $10 minimum size, one bar at a time
python legs/calib.py settle 0xWALLET [--live]                             # finish a fill the run left open
python legs/calib.py hurdle                                               # measured kept fraction, loss ratio, gap, breakeven
```

Step 3 of `../LIVE-LEG.md`. Ten minimum-size fills following the paper baseline on identical bars, graded from the account
balance and the Hyperliquid print, written to `data/calib.jsonl`. Its one output is the measured breakeven loss rate that
the operator writes into `RULES.md` in place of the published-curve 0.43. Dry-run by default; capped at 10 fills per run.
