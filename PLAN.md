# Plan

PAPER is venue-side equity: a claim on the house's take. The play is to own it at the lowest cost basis, staked, within a burn budget set in advance.

## Thesis

PAPER mints on every losing close's gross loss (research/mint-basis.md); winners pay only the asymmetric-impact haircut. Run trades as **matched pairs** — a long and a short of equal size, closed together once price has moved ≥1%. Each pair has one loser and one winner, so the result is deterministic instead of a coin flip:

- loser loses W and mints 0.98·W·rate PAPER (2% loss fee on solvent closes)
- winner is paid kept·W (kept ≈ 0.886 at a 1% move, unverified)
- cost per PAPER = (1 − kept) / (0.98 · rate) ≈ $0.00116 at the flat rate, against $0.0102 for losing on purpose

Arrival time matters less than the crowd thinks: the decay is gentle (`python tracker/ptrack.py curve`). Waiting until the pool is past $5M costs ~$0.00122–0.0015/PAPER and removes the empty-pool queue, launch congestion and day-one contract risk. See CALM-ENGINEER.md.

## Open questions — answer before committing

| # | Question | If the answer is bad |
|---|---|---|
| a | ~~Does PAPER mint on gross realized loss or on net LP growth?~~ **Resolved 2026-10-05: per-close gross loss, 0.98× on solvent closes** (research/mint-basis.md) | — |
| b | What makes a loss "eligible"? Docs name no hold-time, size or wash rule | Adjust trade shape to qualify |
| c | Relayer priority weights; minimum notional? | Raise notional at lower leverage |
| d | Actual haircut parameters | Measured in phase 2; widen to ±2% if kept < 0.80 |
| e | Is the frontend open to US users? | Stop |
| f | Phase 4 transfer timing | Sets how long capital is locked |

Channels: docs, Discord, @izebel_eth (answering questions in person at the Hyperliquid event 2026-10-05).

## Phased run

Example sizing: $2,000 burn budget. Scale every number to the real budget.

### Phase 0 — setup, no money in (by 10-07)

1. Set the burn budget: money that can go to zero with no exit date.
2. Answer e (US access). If blocked, stop here.
3. Fresh wallet with USDC on Hyperliquid; the relayer pays gas. Type `papertrade.xyz` directly; never follow links.
4. **No predeposit.** Not trading on day one means no reason to hold funds in a brand-new contract.

### Phase 1 — watch (10-08 to about 10-20)

5. 10-08, once predeposit opens: `python tracker/ptrack.py deploy wayback:https://papertrade.xyz/ --wallet <your wallet>` (or a saved page if the trade route carries the tag; see tracker/README.md). Then `python tracker/ptrack.py watch --every 120`.
6. Let the crowd race; their 1000x liquidations fill the pool.
7. **Entry trigger — the tracker prints GO when all hold:** pool ≥ $5M, queue empty, nothing paused, no contract implementation changed since first seen. Sumcap puts the pool at $5M in ~5–14 days.

### Phase 2 — test (one day)

8. Deposit $200. Run 5 pairs at $100 margin per leg, 10x ($1,000 notional each side).
9. For each pair check:
   - PAPER minted = 0.98 × loss × current rate. If not, stop.
   - kept = winner payout ÷ raw gain. If below 0.80, widen the close trigger to ±2%. Re-run `ptrack.py curve --kept <measured>`.

### Phase 3 — farm (about 3–4 weeks)

10. Working capital: $1,000 margin per leg, 10x, $10k notional each side.
11. Cycle: open long + short together → wait for a ≥1% move in either direction → close both → stake the minted PAPER immediately → reopen. BTC and ETH both, about 4–10 cycles a day.
12. Per cycle at a 1% move: loser −$100, mints ~9,800 PAPER at the flat rate (fewer as the pool grows); winner +~$88.60; net cost ~$11.40.
13. $2,000 ÷ $11.40 ≈ 175 cycles → ~1.5–1.7M PAPER, depending on rate decay.
14. Stay at 10x: the bust price is ~9.95% away, so a 1% close never nears it. More leverage buys nothing here.
15. Log every cycle (open/close prices, loss, payout, PAPER minted) — the realized cost per PAPER is the number that matters.

### Phase 4 — run as the house

16. Weekly: claim staked USDC; yield on cost = USDC/yr ÷ (PAPER × cost per PAPER).
17. Bull ≈ $50M/yr to stakers over 2–5B supply; bear ≈ $5M/yr.

### Phase 5 — endgame

18. When PAPER transfers open (no date), hold the yield or sell to buyers who paid ≥1¢.

## Stop rules

| Trigger | Action |
|---|---|
| Minted PAPER ≠ formula | Stop |
| Winning leg queued > 24h (tracker STOP) | Pause until cleared |
| Realized cost > $0.004/PAPER over 50 cycles | Stop, re-plan |
| Staker USDC in weeks 1–2 annualizes < 3× cost | Stop farming, hold staked PAPER |
| Exploit, pause, contract upgrade, or mint/haircut parameter change (tracker STOP) | Withdraw undeployed funds |
| Burn budget spent | Stop. No top-ups. |

Skip PaperDAO / $PULP: founder-disavowed, opaque treasury, and its pooled-size edge is available solo.

## Risks specific to pairs

- Pairs are allowed by the docs as written, but they are deliberate loss farming. The owner controls haircut parameters and can upgrade the contracts behind a timelock — the tracker's implementation check is the tripwire.
- Phase 1 of launch is frontend-only, so cycles are manual clicks; scripting waits for the open-contract phase.
- If volume never arrives, cheap PAPER earns little.

## Forecast

The flat zone (LP < $2M) is exhausted within the first day of live trading — P = 0.60. Resolves on the LP balance at 2026-10-11 00:00 UTC.
