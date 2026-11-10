# Paper leg rules — frozen 2026-11-07

The operator defines the loss. Nothing below changes on one day's numbers.

## The board

Two numbers per leg per UTC day: **resolved count** and **loss rate**. The daily review is `/board` in Claude Code, which prints `python legs/paperleg.py review` verbatim and nothing else.
The third number, the paper-to-live gap, appears when the live leg runs (live loss rate minus paper loss rate, same bars).

## Call type

- Markets: BTC and ETH on Hyperliquid perps (the only two papertrade lists).
- Unit: one 15-minute bar. 192 bar-market slots a day, so 100 distinct calls a day is a floor, not a target.
- A call is made inside the first 120 seconds of a bar, from the last **closed** bar only. Later than that, the bar is skipped and logged. The leg never reads the bar it is calling.
- Grader: the Hyperliquid `candleSnapshot` print for that bar, read after the bar's end time. Nothing else grades. No "it would have filled."
- One bit: long is right if close > open; short is right if close < open. **A tie is a loss.**
- Duplicates (same leg, market, bar) count once; the ledger key enforces it.
- Horizon: 15 minutes, inside any review cycle. Anything slower goes to another ledger.

## Legs (the frozen rules)

| Leg | Rule for the bar that just opened |
|---|---|
| `mom1` | same direction as the last closed bar (tie → long) |
| `rev1` | opposite of the last closed bar (tie → short) |
| `long` | always long (the null leg; measures drift and the grader itself) |

`mom1` is the **baseline**. `rev1` and `long` run as forward shadows. All three are on the board; none is tuned.

## Burn-in and promotion to live

Papertrade's house take is the hurdle, not zero. A winner keeps about 74% of a 0.1% move and about 88% of a 1% move, so breakeven is a loss rate of **0.43** at 15-minute move sizes.

- A leg is eligible for live only after **5 full UTC days** with ≥ 100 resolved calls a day **and** a batch loss rate **< 0.43**.
- Live starts at the venue's minimum size, one position per call, and runs beside the paper leg on the same bars.
- A challenger replaces the baseline only when its batch loss rate beats the baseline's over the same 5-day batch. The batch is the unit of change.

## Kill rules (written before the first call)

| Trigger | Action |
|---|---|
| Leg loss rate ≥ 0.50 over a 5-day batch with ≥ 500 resolved | Leg is killed; stays on the board as dead |
| Grader disagreement: a bar's candle print changes between reads | Stop every leg; the grader is broken |
| Live leg: gap (live − paper loss rate) > 0.10 over a batch | Live leg stops; paper continues |
| Live leg: realized cost per call > 2× the published haircut | Live leg stops |
| Any day with < 100 resolved for infrastructure reasons | Not a signal; fix the machine, do not touch the rule |

## Separate ledgers

- `legs/data/calls.jsonl` — the board. Forward only.
- `legs/data/backtest.jsonl` — the frozen rules replayed on past candles. Sanity only. Never on the board.
- `legs/data/tick.log` — machine log; never scored.
