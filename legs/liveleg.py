"""Live leg client for papertrade (HyperEVM, contract set 2). Dry-run by default; nothing is sent without --live.

    python liveleg.py state                         # relayer trading state: minimums, pauses, leverage caps
    python liveleg.py account 0xWALLET              # live account snapshot: balance, session keys, open positions
    python liveleg.py keygen                        # new session key -> data/session.json (chmod yourself; never commit)
    python liveleg.py register 0xWALLET [--live]    # wallet signs RegisterSessionKey; wallet key from $PAPERTRADE_WALLET_KEY, used once, never stored
    python liveleg.py open 0xWALLET BTC long [--live]   # one minimum-size open ($10 margin at the smallest leverage that clears the notional floor)
    python liveleg.py close 0xWALLET 123 [456..] [--live]
    python liveleg.py probe                         # sends one Close signed by a random unregistered key; expects 403 unauthorized_intent

Protocol (from the community-client audit of 2026-11-07, legs/../LIVE-LEG.md): EIP-712 intents signed off-chain,
POST https://exchange.papertrade.xyz/intents {"action", "signed"}; the relayer's BatchExecutor is the only path on-chain.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SESSION = DATA / "session.json"
NONCES = DATA / "nonces.json"
AUDIT = DATA / "live-audit.jsonl"

BASE = "https://exchange.papertrade.xyz"
USER_AGENT = "papertrade-legs/0.1 (python-urllib)"  # the relayer front returns 403 to the bare urllib agent
CHAIN_ID = 999
EXCHANGE = "0x6cd5661646289fb6e65ea5c032310fded797d0a2"
INSTRUMENTS = {"BTC": 0, "ETH": 1}
WAD = 10**18
INTENT_TTL = 3600
SESSION_TTL = 30 * 86400
INTENT_ID_TAG = keccak(text="papertrade:intent-id:v2")

DOMAIN = {"name": "String", "version": "1", "chainId": CHAIN_ID, "verifyingContract": EXCHANGE}
TYPES = {
    "RegisterSessionKey": [
        {"name": "user", "type": "address"}, {"name": "key", "type": "address"}, {"name": "expiry", "type": "uint64"},
        {"name": "feeAddress", "type": "address"}, {"name": "nonce", "type": "uint256"}, {"name": "deadline", "type": "uint64"},
    ],
    "OpenPosition": [
        {"name": "user", "type": "address"}, {"name": "instrumentId", "type": "uint32"}, {"name": "isLong", "type": "bool"},
        {"name": "size", "type": "uint128"}, {"name": "leverage", "type": "uint32"}, {"name": "useDebt", "type": "bool"},
        {"name": "nonce", "type": "uint256"}, {"name": "deadline", "type": "uint64"},
    ],
    "Close": [
        {"name": "user", "type": "address"}, {"name": "positionIds", "type": "uint256[]"},
        {"name": "nonce", "type": "uint256"}, {"name": "deadline", "type": "uint64"},
    ],
}
ACTIONS = {"RegisterSessionKey": "registerSessionKey", "OpenPosition": "openPosition", "Close": "closePositions"}


# ----------------------------------------------------------------------------- relayer http

def get(path: str) -> dict:
    req = urllib.request.Request(BASE + path, headers={"accept": "application/json", "user-agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def post(path: str, body: dict) -> tuple[int, object]:
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "accept": "application/json", "user-agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as err:
        raw = err.read().decode(errors="replace")
        try:
            return err.code, json.loads(raw)
        except ValueError:
            return err.code, raw


def trading_state() -> dict:
    return get("/state/trading")


def account_snapshot(wallet: str) -> dict:
    """First `wallet` event of the SSE stream is the full snapshot."""
    req = urllib.request.Request(f"{BASE}/state/user/live?wallet={wallet.lower()}", headers={"accept": "text/event-stream", "user-agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        event, data = None, []
        deadline = time.time() + 25
        while time.time() < deadline:
            line = resp.readline().decode().rstrip("\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif line == "":
                if event == "wallet" and data:
                    return json.loads("".join(data))
                event, data = None, []
    raise RuntimeError("no wallet snapshot within 25s")


# ----------------------------------------------------------------------------- signing

def wire(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.startswith("0x"):
        return value.lower()
    if isinstance(value, list):
        return [wire(v) for v in value]
    return value


def sign_intent(primary: str, message: dict, private_key: str) -> dict:
    typed = {"types": TYPES_WITH_DOMAIN(primary), "primaryType": primary, "domain": DOMAIN, "message": message}
    signable = encode_typed_data(full_message=typed)
    signed = Account.sign_message(signable, private_key=private_key)
    signer = Account.from_key(private_key).address
    digest = bytes(signed.message_hash)
    intent_id = "0x" + keccak(INTENT_ID_TAG + digest + bytes.fromhex(signer[2:])).hex()
    body = {k: wire(v) for k, v in message.items()}
    body.update({"v": str(signed.v), "r": "0x" + signed.r.to_bytes(32, "big").hex(), "s": "0x" + signed.s.to_bytes(32, "big").hex()})
    return {"action": ACTIONS[primary], "signed": body, "intentId": intent_id, "signer": signer.lower()}


def TYPES_WITH_DOMAIN(primary: str) -> dict:
    return {
        "EIP712Domain": [
            {"name": "name", "type": "string"}, {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"},
        ],
        primary: TYPES[primary],
    }


# ----------------------------------------------------------------------------- local state

def load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save_json(path: Path, obj) -> None:
    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps(obj, indent=1))


def next_nonce(user: str, lane: str = "session") -> int:
    nonces = load_json(NONCES, {})
    key = f"{CHAIN_ID}:{EXCHANGE}:{lane}:{user.lower()}"
    n = nonces.get(key) or (secrets.randbits(24) or 1) * 256
    nonces[key] = n + 1
    save_json(NONCES, nonces)
    return n


def session_key() -> dict:
    s = load_json(SESSION, None)
    if not s:
        sys.exit("no session key: run `liveleg.py keygen`, then `register`")
    return s


def audit(entry: dict) -> None:
    DATA.mkdir(exist_ok=True)
    with AUDIT.open("a") as fh:
        fh.write(json.dumps({"at": int(time.time()), **entry}) + "\n")


# ----------------------------------------------------------------------------- units

def minimum_unit(state: dict) -> tuple[int, int]:
    """Smallest admissible open: minimum margin at the smallest leverage that clears the notional floor."""
    margin = int(state["minimumTradeSizeRaw"])
    notional = int(state["minimumOpenNotionalRaw"])
    lev = -(-notional // margin)
    cap = int(state.get("maximumLeverage") or 0) or 10**9
    if lev > cap:
        raise RuntimeError(f"minimum notional needs {lev}x but leverage cap is {cap}x")
    return margin, lev


def check_open(state: dict, instrument_id: int, leverage: int) -> None:
    if state.get("tradingPaused"):
        raise RuntimeError("tradingPaused")
    ic = state.get("intakeControls")
    if ic and "openPosition" in (ic[2] or []):
        raise RuntimeError("relayer has paused openPosition intake")
    inst = next(i for i in state["instruments"] if i[0] == instrument_id)
    if not inst[4] or inst[5] or inst[8]:
        raise RuntimeError(f"instrument {instrument_id}: active={inst[4]} paused={inst[5]} closeOnly={inst[8]}")
    if leverage > int(inst[14]):
        raise RuntimeError(f"leverage {leverage} above instrument max {inst[14]}")


# ----------------------------------------------------------------------------- commands

def send(prepared: dict, live: bool, label: str) -> None:
    print(json.dumps({k: prepared[k] for k in ("action", "signed", "intentId")}, indent=1))
    if not live:
        print(f"\nDRY RUN: not sent. Add --live to POST {BASE}/intents")
        audit({"label": label, "live": False, "intentId": prepared["intentId"]})
        return
    status, resp = post("/intents", {"action": prepared["action"], "signed": prepared["signed"]})
    echoed = resp.get("intentId") if isinstance(resp, dict) else None
    match = echoed == prepared["intentId"] if echoed else None
    print(f"\nHTTP {status}: {json.dumps(resp)}\nintentId echoed matches local: {match}")
    audit({"label": label, "live": True, "intentId": prepared["intentId"], "status": status, "response": resp, "idMatch": match})


def cmd_state(_: argparse.Namespace) -> None:
    s = trading_state()
    margin, lev = minimum_unit(s)
    ic = s.get("intakeControls") or [None, "0", []]
    print(f"indexedThroughBlock {s['indexedThroughBlock']}  tradingPaused {s['tradingPaused']}  offHours {s.get('offHours')}  exchange {s.get('exchange')}")
    print(f"minimum margin ${int(s['minimumTradeSizeRaw']) / WAD:,.2f}  minimum notional ${int(s['minimumOpenNotionalRaw']) / WAD:,.2f}  leverage {s.get('minimumLeverage')}..{s.get('maximumLeverage')}")
    print(f"minimum PAPER stake {int(ic[1]) / WAD:,.0f}  paused intake actions {ic[2]}")
    for i in s["instruments"]:
        print(f"  {i[1]}: active={i[4]} paused={i[5]} closeOnly={i[8]} maxLev={i[14]} maxPos=${int(i[15]) / WAD:,.0f} baseRate={int(i[17]) / WAD:.2f}")
    print(f"\nSMALLEST LIVE UNIT: ${margin / WAD:.0f} margin x {lev}x = ${margin * lev / WAD:,.0f} notional (bust ~{100 / lev:.1f}% away)")


def cmd_account(a: argparse.Namespace) -> None:
    snap = account_snapshot(a.wallet)
    keys = snap.get("sessionKeys") or []
    print(f"wallet {snap.get('address')}  revision {snap.get('accountRevision')}  indexed block {snap.get('indexedThroughBlock')}")
    print(f"balance ${int(snap.get('balance', 0)) / WAD:,.2f}  queued ${int(snap.get('queued', 0)) / WAD:,.2f}  locked ${int(snap.get('locked', 0)) / WAD:,.2f}")
    p = snap.get("paper") or {}
    print(f"PAPER balance {int(p.get('balance', 0)) / WAD:,.0f}  staked {int(p.get('staked', 0)) / WAD:,.0f}")
    print(f"session keys: {[(k, time.strftime('%Y-%m-%d', time.gmtime(int(e)))) for k, e in keys]}")
    for pos in snap.get("openPositions") or []:
        print(f"  position {pos[0]} inst={pos[1]} long={pos[2]} margin=${int(pos[5]) / WAD:.2f} lev={pos[6]} entry={pos[4]} bust={pos[7]}")
    if a.json:
        print(json.dumps(snap, indent=1))


def cmd_keygen(_: argparse.Namespace) -> None:
    if SESSION.exists():
        sys.exit(f"{SESSION} exists; move it away first")
    acct = Account.create()
    save_json(SESSION, {"address": acct.address.lower(), "privateKey": acct.key.hex(), "created": int(time.time()), "registered": None})
    print(f"session key {acct.address.lower()} -> {SESSION}\nIt can open and close only. Register it with `liveleg.py register 0xWALLET`.")


def cmd_register(a: argparse.Namespace) -> None:
    wallet_key = os.environ.get("PAPERTRADE_WALLET_KEY")
    if not wallet_key:
        sys.exit("set PAPERTRADE_WALLET_KEY for this one command only; it is never written to disk")
    if Account.from_key(wallet_key).address.lower() != a.wallet.lower():
        sys.exit("PAPERTRADE_WALLET_KEY does not match the wallet given")
    s = session_key()
    expiry = int(time.time()) + SESSION_TTL
    msg = {"user": a.wallet.lower(), "key": s["address"], "expiry": expiry, "feeAddress": "0x" + "00" * 20,
           "nonce": next_nonce(a.wallet), "deadline": int(time.time()) + INTENT_TTL}
    prepared = sign_intent("RegisterSessionKey", msg, wallet_key)
    send(prepared, a.live, "register")
    if a.live:
        s["registered"] = {"wallet": a.wallet.lower(), "expiry": expiry, "intentId": prepared["intentId"]}
        save_json(SESSION, s)
        print("confirm with `liveleg.py account 0xWALLET` once the batch executes: the key must appear under session keys")


def cmd_open(a: argparse.Namespace) -> None:
    s = session_key()
    state = trading_state()
    margin, lev = minimum_unit(state)
    inst = INSTRUMENTS[a.market.upper()]
    check_open(state, inst, lev)
    msg = {"user": a.wallet.lower(), "instrumentId": inst, "isLong": a.side == "long", "size": margin, "leverage": lev,
           "useDebt": False, "nonce": next_nonce(a.wallet), "deadline": int(time.time()) + INTENT_TTL}
    print(f"open {a.market.upper()} {a.side}: ${margin / WAD:.0f} x {lev}x = ${margin * lev / WAD:,.0f} notional, session key {s['address']}")
    send(sign_intent("OpenPosition", msg, s["privateKey"]), a.live, f"open:{a.market.upper()}:{a.side}")


def cmd_close(a: argparse.Namespace) -> None:
    s = session_key()
    ids = [int(x) for x in a.position_ids]
    if not 1 <= len(ids) <= 12:
        sys.exit("1 to 12 position ids per close intent")
    msg = {"user": a.wallet.lower(), "positionIds": ids, "nonce": next_nonce(a.wallet), "deadline": int(time.time()) + INTENT_TTL}
    send(sign_intent("Close", msg, s["privateKey"]), a.live, f"close:{ids}")


def cmd_probe(_: argparse.Namespace) -> None:
    """Negative probe: a Close signed by a key nobody registered, for a random user. The relayer should reject it as
    unauthorized_intent (403). Any 400 invalid_intent means our encoding is wrong. No funds, no identity involved."""
    throwaway = Account.create()
    user = Account.create().address.lower()
    msg = {"user": user, "positionIds": [1], "nonce": (secrets.randbits(24) or 1) * 256, "deadline": int(time.time()) + INTENT_TTL}
    prepared = sign_intent("Close", msg, throwaway.key.hex())
    status, resp = post("/intents", {"action": prepared["action"], "signed": prepared["signed"]})
    print(f"HTTP {status}: {json.dumps(resp)}")
    code = (resp.get("code") or resp.get("error")) if isinstance(resp, dict) else None
    verdict = "PASS: relayer parsed the intent and rejected the unregistered key" if code == "unauthorized_intent" else "CHECK: unexpected response"
    print(verdict)
    audit({"label": "probe-unauthorized", "live": True, "status": status, "response": resp})


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("state").set_defaults(fn=cmd_state)
    x = sub.add_parser("account"); x.add_argument("wallet"); x.add_argument("--json", action="store_true"); x.set_defaults(fn=cmd_account)
    sub.add_parser("keygen").set_defaults(fn=cmd_keygen)
    x = sub.add_parser("register"); x.add_argument("wallet"); x.add_argument("--live", action="store_true"); x.set_defaults(fn=cmd_register)
    x = sub.add_parser("open"); x.add_argument("wallet"); x.add_argument("market", choices=["BTC", "ETH", "btc", "eth"]); x.add_argument("side", choices=["long", "short"]); x.add_argument("--live", action="store_true"); x.set_defaults(fn=cmd_open)
    x = sub.add_parser("close"); x.add_argument("wallet"); x.add_argument("position_ids", nargs="+"); x.add_argument("--live", action="store_true"); x.set_defaults(fn=cmd_close)
    sub.add_parser("probe").set_defaults(fn=cmd_probe)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
