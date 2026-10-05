# tracker

On-chain watcher for the papertrade launch: pool size, queue, pause and upgrade state, PAPER supply, staking and every mint. Prints the PLAN.md entry gate (GO / WAIT / STOP) on each snapshot.

## Run book

```
# 10-08, once predeposit opens. papertrade.xyz is blocked on this network, so capture it through the Wayback Machine:
python ptrack.py deploy wayback:https://papertrade.xyz/ --wallet 0xYOUR_WALLET
# if the tag lives on the trading route instead, try that URL, or save the page source from any machine that can reach it:
python ptrack.py deploy saved-page.html --wallet 0xYOUR_WALLET

python ptrack.py snap                 # one snapshot
python ptrack.py watch --every 120    # loop
python ptrack.py curve --kept 0.886   # mint rate and pair cost per PAPER by pool size
```

`deploy` decodes the app's `<meta name="papertrade-runtime-deployment">` tag (base64 JSON: exchange, paper, paperStaking, depositProxyFactory, collateral) into `deployment.json`, validates chain 999, and starts the mint scan at the current head. On 2026-10-05 the live landing page carried no tag yet.

## What it reads

| Signal | Source |
|---|---|
| Pool (`trackedLpUsd`), tail progress, `sideBucket`, pause flags | Exchange getters — every scalar view in the verified ABI, or the docs-named getters when no ABI is found |
| Queue | Any getter named queue / debt / sideBucket that is non-zero. Docs: losses park in `sideBucket` while the queue is non-empty |
| PAPER supply, staked | `paper.totalSupply()`, `paper.balanceOf(paperStaking)` |
| Mints | PAPER `Transfer` events from `0x0`, scanned in 1,000-block chunks, cursor 15 blocks behind head |
| Upgrades | EIP-1967 implementation slot of every contract, compared with the first snapshot |

ABI: Sourcify for the proxy's implementation (never the proxy's admin ABI). If the contracts are verified on hyperevmscan.io instead, save the ABI JSON as `abi/exchange.json` and it is used directly.

## Known limits

- **Units unverified.** `*Usd` getters are scaled by the collateral's EVM decimals unless `deployment.json` sets `usdDecimals`. Confirm against the first test pair before trusting the GO line.
- **Cash held is n/a.** The collateral contract (`0x6b9e…0a24`) is a HyperCore deposit bridge with no `balanceOf`; pool size comes from `trackedLpUsd` only.
- **No historical state on HyperEVM RPCs,** so the contract creation block can't be searched; the scan starts at the head when `deploy` runs (PAPER cannot mint before live trading on 10-10).
- **Public RPCs rate-limit.** The client rotates across five endpoints; set `PTRACK_RPC` to put a private endpoint first.

Data lands in `data/` (gitignored): `snapshots.jsonl`, `mints.jsonl`, `state.json`.

Tests: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q test_ptrack.py`
