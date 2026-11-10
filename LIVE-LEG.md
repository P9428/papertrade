# Live leg on papertrade — the three gates

Status as of 2026-11-09 (gates read 2026-11-07; step 3 and the session key added 2026-11-09). The paper leg (`legs/paperleg.py`) runs regardless; the live leg runs beside it on the same bars once a rule clears burn-in (`legs/RULES.md`).

## Gate 1 — the smallest size the venue allows: CLOSED

The venue's relayer publishes its admission limits live at `GET https://exchange.papertrade.xyz/state/trading`. Read on 2026-11-07 (block 50646293):

| Limit | Value |
|---|---|
| Minimum margin (`minimumTradeSizeRaw`) | $10 |
| Minimum open notional (`minimumOpenNotionalRaw`) | $500 (was $10,000 at launch, $1,000 by mid-October) |
| Leverage | 1 to 1000x, both instruments |
| Max position notional | $10M |
| Minimum PAPER stake | 1,000 PAPER |
| Paused intake actions | none |

**Smallest live unit: $10 margin at 50x = $500 notional.** Bust is 2.0% away, so a 15-minute call is rarely liquidated but not never; a liquidation counts as a loss like any other.

The Exchange contract itself holds no minimum (its `instruments(uint32)` struct has none; its 103 selectors were recovered from bytecode, 58 named via the openchain signature database). The minimum is enforced by the relayer at admission, which is why it must be read from the endpoint above before every session. `python legs/liveleg.py state` does this.

Cost per minimum call at 15-minute move sizes: a 0.1% move on $500 is $0.50 raw. A loser loses $0.50 and mints about 48 PAPER at the current 95 PAPER/$ rate. A winner keeps about 74% ($0.37). At a 50% hit rate the expected cost is about $0.065 a call, or about $6.50 a day for 100 calls.

## Gate 2 — no official API: CLOSED (path verified, first fill pending)

Papertrade has no documented API, but the frontend talks to a relayer with a stable JSON interface, and the contracts accept intents only from that relayer's BatchExecutor. Four community repos were audited read-only (findings in the session scratchpad; summary here). All three code repos emit the same wire format, and it was confirmed against two real mainnet Close intents.

The path:

1. Sign an EIP-712 intent off-chain. Domain `{name: "String", version: "1", chainId: 999, verifyingContract: Exchange proxy}`. Structs `OpenPosition`, `Close`, `RegisterSessionKey` (fields in `legs/liveleg.py`).
2. `POST https://exchange.papertrade.xyz/intents` with `{"action": "openPosition" | "closePositions" | "registerSessionKey", "signed": {fields, v, r, s}}`. Uints as decimal strings, hex lowercase, `v` as "27"/"28".
3. Receipt `{intentId, action, state: "queued"...}`. The intent id is `keccak(keccak("papertrade:intent-id:v2") || digest || signer)`; the client checks the echoed id against its own.
4. Execution is asynchronous through the relayer's batch; outcomes arrive on the SSE stream `GET /state/user/live?wallet=`.

A session key signs opens and closes. It cannot withdraw, stake, or claim. The wallet key signs only the one `RegisterSessionKey` intent and never needs to be on the trading box.

Evidence gathered today:

- `legs/test_liveleg.py` recovers the registered session key and reproduces both on-chain intent ids from the SDK's mainnet fixture (tx `0xde30ba04…f1d9`). 3 tests pass.
- `python legs/liveleg.py probe` sent one Close signed by a random unregistered key for a random user. The relayer answered `HTTP 403 {"code": "unauthorized_intent"}`. A malformed body would have been `400 invalid_intent`. The wire format is accepted.
- No repo shows a confirmed submission after the 2026-10-21 contract set 2 upgrade. Addresses and domain did not change (same proxies), but the first live step is still a single minimum-size probe open and close.

`legs/liveleg.py` is dry-run by default. Every command prints the exact body and intent id and sends nothing without `--live`. Every live send is appended to `legs/data/live-audit.jsonl`.

Operator steps to the first fill:

```
python legs/liveleg.py keygen                       # session key -> legs/data/session.json (gitignored)
# deposit >= 11 USDC to the wallet's papertrade account through the app (1 USDC first-time activation fee)
set PAPERTRADE_WALLET_KEY=0x...                     # this shell only
python legs/liveleg.py register 0xWALLET --live     # wallet signs once; key is never written to disk
set PAPERTRADE_WALLET_KEY=
python legs/liveleg.py account 0xWALLET             # wait until the session key is listed
python legs/liveleg.py open 0xWALLET BTC long --live
python legs/liveleg.py account 0xWALLET             # position id
python legs/liveleg.py close 0xWALLET <id> --live
```

Known gaps in the client: it does not yet follow the SSE stream for intent outcomes (poll `account` instead), does not send the frontend build header (no client has needed it), and does not auto-renew the 30-day session key.

Status 2026-11-09: the session key exists (`keygen` run; `legs/data/session.json`, gitignored, unregistered). Everything up to the deposit and the wallet's one signature is prepared. The two operator steps that remain are the deposit through the app and `register --live` with the wallet key in the shell.

## Step 3 — the calibration ledger (written before it runs)

The single probe above proves the path. It does not measure the haircut. Ten minimum-size fills do, and they are **not** the live leg of `legs/RULES.md`: that leg exists only after a paper rule clears burn-in. These ten are a calibration ledger, separate from the board, whose only output is the number the operator needs before the first 5-day batch closes on 2026-11-12.

`legs/calib.py` runs it. One fill per bar, one position open at a time, $10 margin at the smallest leverage that clears the venue's notional floor (50x today), following the paper baseline `mom1`'s call for that bar so paper and live are graded on identical bars and directions. Hard cap of 10 fills per run, in the code; the operator raises it, the machine does not.

What each row records, all read from the account balance and the chain print, nothing modeled:

| field | what it measures |
|---|---|
| `fill_delay_s` | intent sent to position visible: the relayer batch latency |
| `mid_at_call`, `hl_mid_at_send`, `entry_raw` | the paper mid, the Hyperliquid mid at send, the venue's entry mark: entry slip |
| `paper_bit` vs `live_bit` | direction right against the Hyperliquid close vs net USD > 0 on the venue: the paper-to-live gap, per bar |
| `kept` | net USD ÷ raw move on the notional, winners: the fraction the venue pays out |
| `loss_ratio` | the same for losers: what a losing move actually costs |
| `paper_minted` | PAPER credited on the fill |
| `off_hours` | which haircut curve the relayer said was in force |

`python legs/calib.py hurdle` prints the ledger's measured breakeven, `kept / (kept + loss_ratio)`, next to the 0.43 that `RULES.md` carries from the published curve. The operator writes the measured number into `RULES.md` by hand; the tool never does, and nothing on the board changes until the operator does.

Stop conditions inside the tool: a liquidation before close ends the run; an unfilled or unresolved intent ends the run and `settle` finishes it later; `tradingPaused` or a paused instrument refuses the open. Cost at the published curve: about $0.065 expected per fill, $10 worst case per fill on a bust.

Operator sequence after the probe fill:

```
python legs/calib.py run 0xWALLET --fills 10 --markets BTC ETH --live   # ~2.5 hours, one bar at a time
python legs/calib.py settle 0xWALLET --live                               # only if the run stopped on an open fill
python legs/calib.py hurdle                                               # the measured number, before 2026-11-12
```

Dry run (`--live` omitted) sends nothing, waits for the real paper call, and grades the paper side only; rows are marked `dry`.

## Gate 3 — US access: CLOSED on the venue's side, open on the operator's

The live frontend bundle (216 chunks, 3.9 MB, read 2026-11-07; `research/raw/bundle-findings-2026-11-07.md`) and every docs page were searched for any region, country, sanctions, VPN, eligibility or terms-acceptance logic. None exists. There is no terms-of-service, legal or privacy page on papertrade.xyz, exchange.papertrade.xyz or docs.papertrade.xyz; every such path returns 404 and the docs sitemap has none. The app and its public JSON were served in full to a US Cloudflare edge, and the `POST /intents` probe from this machine was answered on its merits (unauthorized key), not refused by origin.

So the venue imposes no access restriction and asks for no acceptance. What remains is not a venue gate: it is the operator's own judgment on trading an unregistered offshore perps venue from the US. The machine cannot close that one. The intake gates that do exist are per-action and server-side: `tradingPaused`, per-market pause, `intake_action_paused`, `sessionKeyLimit`, `noDeposit`. `liveleg.py state` shows them.

Also recovered from the bundle: the frontend's compiled deployment config names the collateral as the HyperCore deposit bridge `0x6b9e…0a24` (6 decimals) and already carries the set-2 holdback parameters (standard 0.75–6 bps, holdback 3.597; off-hours 0.3–10 bps, holdback 6.085, cubic fall). The relayer state flag `offHours` was true at 17:30 UTC on a Friday, so the off-hours curve, which keeps less on small moves, was live during US afternoon hours. The paper leg's breakeven of 0.43 should be re-derived against the measured live gap, not the published standard curve.

## What is still true from PLAN.md

- The matched-pair farm and the 100-calls machine are different plays on the same venue. Pairs are deterministic and produce no bit; the live leg here is directional and produces one bit per call. Both mint PAPER on the losing side.
- Pool is $4,999,870 on 2026-11-07, $130 under the PLAN.md entry line, queue empty, trading not paused. `python tracker/ptrack.py snap`.
- PAPER supply is 9.26B, above the 2–5B range PLAN.md assumed for staker yield math. Recompute before Phase 4.
