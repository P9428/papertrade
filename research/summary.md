# papertrade.xyz — research summary (2026-10-05)

Official docs (docs.papertrade.xyz) failed to load (SSL error); parameters below are as quoted by Sumcap, Bankless, Blockworks, Blocmates, iq.wiki and the official launch post. Items marked UNVERIFIED come from community posts only.

## Venue

- Fully on-chain synthetic perps on Hyperliquid's HyperEVM. Built by @izebel_eth and @blurr (pseudonymous). Audit: Guardian Audits (contracted 2026-05-31).
- Every trade is a synthetic swap against one LP at Hyperliquid BBO mid, read via L1 precompiles. No orderbook, spread, funding or open fee. Up to 1000x.
- Launch markets BTC and ETH; $10M position cap per user (UNVERIFIED, @0xTowhid).
- Winners: asymmetric impact haircut, 0.2 bps deadband/fee. Keeps 25% of a 0.0095% BTC move, 50% of 0.0235%, 88.6% of 1% (Sumcap, Rollbit-borrowed parameters).
- Losers: full loss to the LP. If the LP can't pay, winners queue FIFO until new losses arrive.
- Liquidation at 1000x after about a 5 bps adverse move (Sumcap).

## PAPER

- Supply starts at 0. No pre-mint, team, VC, airdrop or vesting. Minted only on realized losses and liquidations.
- Flat 100 PAPER per $1 of loss mint basis while tracked LP < $2M (including underwater), i.e. 1¢/PAPER. Above $2M, asymptotic decay set by `tailScaleUsd`. Decay table 88/$1 at $10M, 51 at $50M, 30 at $100M (UNVERIFIED, @NPC_68).
- Staked PAPER earns USDC. LP < $5M: protocol revenue 50% stakers / 50% frontend. LP > $5M: excess LP gain swept to stakers (99% stakers / 1% frontend), via keeper `pushStakerFees()`.
- Non-transferable at launch beyond stake/unstake; transfers in phase 4, no date.

## Sumcap simulation (608 scenarios, HL max-leverage traders as proxy)

- LP solvent in 100% of scenarios; max unpaid queue $61,974 / 70 trades; no debt survived its day.
- Time to $5M cap: ~5 days at full flow, ~14 days at 25% flow (slowest 36 days).
- 73¢ lost per $1 of margin at full flow; trader net losses $47M–$256M over 289 days, nearly all to stakers.
- 1000x cohort: 80% (BTC) / 91% (ETH) liquidated.
- Not modeled: PAPER price feedback, loss farming, papertrade's own calibration.

## Launch (official post 2026-10-01)

| Date | Phase |
|---|---|
| 10-08 | Phase 0: predeposit only, trading paused. No advantage to depositing earlier within the window. |
| 10-10 | Phase 1: live trading via papertrade.xyz frontend and whitelisted relayers only; contract closed to direct calls. Intent queue weighted by transaction type and notional, indifferent to account; liquidations outrank opens; weights adaptive. Pending trades cancellable. PAPER minting starts. |
| later | Phase 2 open contract · Phase 3 builder codes (1% frontend fee) · Phase 4 PAPER transfers |

Expect heavy congestion, worst for small notional.

## Red flags

- Scam domains are active; only `papertrade.xyz` is official. Solana token "PAPERTRADE" (DfG8ZwbEGAm6jYsPhhDcs86Wxs9jo3MmS7mSdiXyDdiv, ~$1.3K mcap) is fake.
- 2026-09-05: 12 people found the mainnet test deployment and deposited; funds locked pending return.
- PaperDAO / $PULP (@paperdao_xyz, daos.world, Robinhood Chain, 50 ETH target, tiers 0.25/0.1 ETH): @izebel_eth on 2026-10-03: "blurr and i have no association with paperdao". Days-old account, private strategies, coordinated promotion.
- Pseudonymous team; parameters adjustable post-launch; PAPER exit date undefined.
- US access not confirmed — check terms.

## Sources

- https://x.com/papertrade_xyz
- https://docs.papertrade.xyz/
- https://www.bankless.com/read/papertrade-turns-liquidations-into-ownership
- https://blockworks.com/newsletter/0xresearch/issue/post_01ac4b23-c301-4375-b623-916bee42cadf
- https://www.sumcap.xyz/blog/the-house-always-wins
- https://www.blocmates.com/articles/papertrade-the-perp-venue-that-pays-for-losses
- https://iq.wiki/wiki/papertrade
- https://www.btcc.com/en-US/news/flash-article/119815
- https://www.paperdao.xyz/ · https://github.com/iam-rekt/paperdao-xyz
- https://x.com/tomwanhh/status/2054558458569961687
