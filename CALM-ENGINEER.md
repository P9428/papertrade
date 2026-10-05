# Calm Engineer ledger — papertrade launch

Situation: papertrade.xyz goes live 2026-10-10; PAPER mints only on trader losses. Date: 2026-10-05.

## 0. Stabilise

- Real deadlines: predeposit window opens 10-08; live trading 10-10. Neither forces a decision today.
- Frozen until the open questions in PLAN.md are answered: any deposit, any PaperDAO/$PULP buy, any link not typed by hand.

## 1. Brutal facts

- PAPER has no market, no transfer date, and a value that depends entirely on future trader losses.
- Value per PAPER per year = staker USDC per year ÷ staked supply. Neither term is known.
- Sumcap's staker flow range is $47M–$256M over 289 days at modeled flow. It does not model loss farming or PAPER price feedback, and it borrows Rollbit's haircut parameters.
- Contract is new (Guardian audit); the team is pseudonymous; parameters are adjustable after launch.
- The crowd is aimed at one thing — the first block of the flat zone — and PaperDAO is marketing exactly that.
- Burn budget: $______ (money that can go to zero with no exit date). Not set yet.

## 2. End state

By 2026-12-31: staked PAPER at a realized all-in cost ≤ $0.002/PAPER, with total losses ≤ the burn budget and every dollar of it accounted for in a fill log.

## 3. Redefine

Stated problem: be first in the block-one race for the 100/$ flat zone.

- **A. Cost per PAPER, not arrival time.** At mid-price with no fees, a no-edge trader with symmetric ≥1% brackets loses only the winner haircut. Expected cost ≈ 0.055W per 50W PAPER, about $0.0011. Deliberate losing in the flat zone costs $0.01. That is a 9x cost gap. The time advantage is small because the decay is gentle: 100/$ under $2M LP, 88/$ at $10M (unverified). Symmetric bracketing at 88/$ costs about $0.00125 — still 8x cheaper than the crowd's flat-zone rate.
- **B. Be the house's distribution, not its customer.** Phase 3 builder codes pay frontends and routers a fee share. That is fee-on-flow with no trading loss at all.
- **C. Own the information.** An on-chain LP, mint-rate and staker-yield tracker decides the stop rule better than anyone guessing from tweets.

Chosen: **A**, with C as its instrument. B is a later option once its terms are public.

Consequence: the launch-day race is not the hill. Farming patiently for weeks at about $0.001 beats fighting the congested first block at $0.01 — provided the mint basis is gross loss.

## 4. Inventory

1. Hyperliquid capture and carry engine on VPS .200 — price, volatility and order-flow context for BTC/ETH
2. X API pay-per-use bearer (`rich/.env`) — sentiment and announcement monitor
3. Foresight board — forecast and resolve the launch claims
4. Dune execute-by-id access
5. Loss-first doctrine — stop rules already part of how you work
6. Ability to read Solidity and build bots
7. The papertrade mainnet testing deployment exists on-chain (found by 12 people in September) — the source may already be readable
8. The official launch post: relayer priority by type and notional, not account
9. Sumcap's 608-scenario simulation and its parameters
10. Founder access tonight (@izebel_eth at the Hyperliquid event)
11. Public community farming math (cost tables, decay table) to check against the contract
12. Time — no deadline forces block-one participation
13. Workstation scheduled-task setup for daily jobs
14. This repo's research and raw pulls
15. The crowd's own behaviour (see 6 below)

## 5. Binding constraint

**Whether PAPER mints on gross realized loss or on net LP growth.** If gross, reframe A works and patience beats the race. If net, every PAPER costs about 1¢ no matter how you trade, and only budget size and timing matter.

## 6. Counterparty orientation

| Party | Wants | Fears | Believes | Expects |
|---|---|---|---|---|
| The crowd / PaperDAO | Max PAPER in the flat zone | Missing the first block | The flat zone is everything and dies in hours | To jam size at high leverage on 10-10 |
| papertrade team | Volume, a solvent LP, a clean launch | MEV wars, an exploit, loss-farming that never refills the LP | Traders lose in aggregate | People to trade through the frontend, at size |
| The LP mechanism | — | Winners when it is empty | — | — |

**Using their energy:** the crowd's 1000x liquidations fill the LP. That clears the winner queue that pays your winning brackets, and it is the revenue stream your staked PAPER collects. Their gambling is your yield.

## 7. Moves and pre-mortem

| Move | It failed because | Fix |
|---|---|---|
| (a) Symmetric ≥1% brackets, 5–20x, BTC/ETH, farmed over weeks | Mint basis is net LP growth, or short-hold losses aren't "eligible" | Read the mint function in the contract before trading; test with 20 small closes first |
| (b) Builder-code frontend or router | Fee terms are small or the official frontend takes the flow | Decide only when phase 3 terms are published |
| (c) LP and yield tracker driving the stop rule | Contract address or events are unreadable | Address is known at predeposit (10-08); read events directly |
| Whole thesis | Volume never arrives, so PAPER earns little | Weekly yield check; stop farming below the threshold |
| Whole thesis | Exploit, rug, or parameter change | Small budget; withdraw on any exploit report |
| Whole thesis | US users blocked by the terms | Check before depositing |

Pre-mortem date: 2027-04-05. "It failed because the cheap PAPER was cheap for a reason — there were no losses to share." Counter: yield tripwire, small budget.

Chosen move: **(a), steered by (c).**

## 8. Contingencies and tripwires

- Plan B: if the mint basis is net LP growth, farm only inside the flat zone with a smaller budget and accept the 1¢ cost, or skip.
- Plan C: hold no position and run the tracker only, then act at phase 4 when PAPER trades.
- Way out: withdraw the undeployed deposit; PAPER already minted stays staked.

| Tripwire | Switch to |
|---|---|
| First 20 closes mint ≠ 100 × gross loss (or the stated curve rate) | Stop symmetric; Plan B |
| A winning close is queued > 24h | Pause new trades until the queue clears |
| Realized cost per PAPER > $0.004 over a rolling 50 closes | Stop and re-plan |
| Staker USDC in week 2 annualizes below 3x your cost per PAPER | Stop farming; hold the staked PAPER |
| Any exploit, pause, or parameter change on the mint curve | Withdraw undeployed funds |
| Cumulative losses reach the burn budget | Stop. No top-ups. |

## 9. Next verifiable steps

1. **10-05 night:** ask @izebel_eth or the Discord question (a): gross loss or net LP growth, and what makes a loss "eligible." Done when an answer is written in PLAN.md.
2. **By 10-07:** find the testing deployment on the HyperEVM explorer and read the mint and haircut code if it is verified. Done when the mint basis is confirmed from source.
3. **By 10-07:** set the burn budget, check US access in the terms, fresh wallet funded with USDC + HYPE on HyperEVM.
4. **10-08:** predeposit; record the contract address; tracker reads LP balance, mint events, queue length.
5. **10-10 onward:** 20 test closes → check the tripwire → scale only if the minted amounts match.

## 10. Debrief (after)

Situation type: ______ Move that worked: ______ Signal I missed: ______
