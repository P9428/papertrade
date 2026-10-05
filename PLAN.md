# Plan

PAPER is venue-side equity: a claim on the house's take. The play is to own it at the lowest cost basis, staked, within a burn budget set in advance.

## Thesis

Trading at mid with no fee, spread or funding, a no-edge trader's expected cost is only the haircut on wins, while every losing close mints PAPER. With symmetric outcomes of size W and an ~11% haircut on ≥1% moves:

- expected cost per trade ≈ 0.5·W·0.11 = 0.055W
- expected mint ≈ 0.5·W·100 = 50W PAPER
- cost ≈ $0.0011/PAPER, against $0.01 for deliberate losing

Holds only if minting is on gross realized loss (open question a), targets are ≥1% moves, and winning closes get paid (LP is $0 at launch, so early wins queue).

See CALM-ENGINEER.md: the edge is cost per PAPER, not block-one arrival — patience beats the launch race if (a) is gross loss.

## Open questions — answer before committing

| # | Question | If the answer is bad |
|---|---|---|
| a | Does PAPER mint on gross realized loss or on net LP growth? | Cost reverts to 1¢/PAPER; only budget size matters |
| b | What makes a loss "eligible"? Min hold time, min size, wash detection? | Adjust trade shape to qualify |
| c | Relayer priority weights; minimum notional? | Raise notional at lower leverage |
| d | Actual haircut parameters | Recompute cost per PAPER |
| e | Is the frontend open to US users? | Stop |
| f | Phase 4 transfer timing | Sets how long capital is locked |

Channels: docs, Discord, @izebel_eth (answering questions in person at the Hyperliquid event 2026-10-05).

## Steps

1. **By 10-07** — answer a–f. Set the burn budget: money that can go to zero with no exit date.
2. **By 10-07** — fresh wallet; USDC to HyperEVM plus HYPE for gas. Type `papertrade.xyz` directly; never follow links.
3. **10-08** — predeposit the full budget through the official frontend.
4. **10-10** — BTC/ETH, 5–20x, symmetric profit-target/stop brackets of about ±1–2%. No 1000x, no sub-0.05% scalps. Notional large enough to clear the relayer queue, within budget.
5. Stake every PAPER as it mints.
6. Track LP on-chain. Past $2M the rate decays; stop when realized cost/PAPER exceeds a third of the conservative one-year yield estimate. Stop at the burn budget regardless of results.
7. Weekly: staker USDC paid ÷ supply → yield on cost. Bull ≈ $50M/yr over 2–5B supply; bear ≈ $5M/yr.
8. Phase 4: hold for yield or sell to late arrivals.

Skip PaperDAO / $PULP: founder-disavowed, opaque treasury, and its pooled-size edge is available solo.

## Forecast

The flat zone (LP < $2M) is exhausted within the first day of live trading — P = 0.60. Resolves on the LP balance at 2026-10-11 00:00 UTC.

## Next build

Once the contract address is public: LP and cost-per-PAPER tracker feeding the foresight board.
