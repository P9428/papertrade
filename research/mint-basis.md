# Mint basis — resolved 2026-10-05

Question (a): does PAPER mint on gross realized loss or on net LP growth?

**Answer: per-close gross realized loss.** Winning closes do not reduce what your losing closes mint.

Source: official docs bundle archived by the Wayback Machine on 2026-10-03 (`raw/docs-bundle-2026-10-03.js`, from `docs.papertrade.xyz/assets/index-ByTNIxKj.js`). papertrade.xyz and docs.papertrade.xyz are blocked on this workstation's network (`safebrowse.io` redirect, TLS failure), so the live site was not read.

## Quotes

> The mint basis is the user's eligible realised loss, not necessarily the cash that immediately credited LP.

> The mint basis is the user's eligible realised loss after any LP-side loss-fee carve. On a solvent loss close the 2% loss-branch fee is carved from LP's side, so PAPER mints on `rawLoss − fee` while tracked LP also advances by that credited amount. On an insolvent close, no fee is taken, the loss can park in `sideBucket`, and PAPER still mints on the realised loss basis even though `trackedLpUsd` is not inflated by the sideBucket park. Liquidations mint on the lost margin in full, regardless of solvency state.

> PAPER mints to your account whenever you close a trade at a loss or get liquidated. Nothing else mints PAPER.

> Insolvent region (tracked LP < 0) and flat region both mint at the full 100 PAPER/$ of eligible loss basis; the tail decays as `100 · (S/(S+H))²` where `H = tailProgressUsd`. Defaults `flatRate=100`, `threshold=$2M`, `S=$120M`.

## What else the docs settle

- **Fees:** solvent losing close mints on 0.98 × loss (2% loss fee goes from the LP's credit to stakers/dev). Insolvent close: no fee, full basis. The trader pays nothing on top of the loss.
- **Decay table confirmed:** 100·(120/(120+H))². LP $10M (H = $8M) → 87.9/$. LP $50M → 51/$. LP $100M → 30.3/$.
- **Eligibility:** the docs name no hold-time, minimum-size or wash-trade rule. "Eligible" appears only as losing closes and liquidations.
- **Haircut:** `scale = (1 − baseRate) / (1 + 1/(move·rateMultiplier) + referenceNotional/(move·positionMultiplier))`, with a 0.2 bps deadband. Same percentage for $100 or $100K — size of position does not matter. Parameter values are not published.
- **Liquidation is a hard bust:** crossing the bust price (about 5 bps before zero equity) forfeits the full margin. At 10x the bust is at a ~9.95% move; at 20x ~4.95%.
- **Positions:** isolated and fixed. No margin top-up, no partial close. No resting take-profit or stop orders are described — closes are manual or scripted through the session key.
- **Caps:** BTC and ETH, up to 1000x, $10M per-user position cap, configurable per-side open-interest caps.
- **Admin:** contracts are upgradeable proxies. The owner, behind a governance timelock, can tune impact and fee parameters, swap relayers and keepers, add markets, and upgrade implementations.
- **Oracle:** `PriceOracle` rejects zero or crossed books but has no deviation, TWAP or lookback breaker. A manipulated BBO can be accepted.
- **Staking:** instant stake and unstake, no cooldown or minimum; USDC accrues continuously.

## Not resolved

- Contract address: injected at runtime as base64 deployment metadata, absent from the archived bundles. Read it from the live page when predeposit opens (10-08), then check verification on hyperevmscan.io.
- Contract source: the docs cite `contracts/src/PaperTokenomics.sol`, `Exchange.sol`, `QueueLib.sol`, `PaperMathLib.sol`, but no public repo link. The docs are the team's description of the code, not the code.
- Haircut parameter values: still Sumcap's Rollbit-borrowed estimate (~88.6% kept on a 1% move).
