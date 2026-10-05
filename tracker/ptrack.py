"""Papertrade pool, queue and mint tracker (HyperEVM).

Reads the deployment the papertrade.xyz app ships in its
`<meta name="papertrade-runtime-deployment">` tag, then snapshots pool size,
queue state, PAPER supply/staking and mint events straight from the chain, and
evaluates the PLAN.md entry gate and stop rules.

    python ptrack.py deploy wayback:https://papertrade.xyz/ [--wallet 0x..]   # or saved page.html, a base64 string, or -
    python ptrack.py snap
    python ptrack.py watch --every 60
    python ptrack.py curve --kept 0.886
"""

from __future__ import annotations

import argparse
import base64
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from eth_abi import decode
from eth_utils import keccak

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
ABI_DIR = HERE / "abi"
DEPLOYMENT = HERE / "deployment.json"
STATE = DATA / "state.json"

RPC_URLS = (  # all checked 2026-10-05 for eth_getLogs over 1000-block ranges
    "https://rpc.hyperliquid.xyz/evm",
    "https://rpc.hypurrscan.io",
    "https://hyperliquid-json-rpc.stakely.io",
    "https://rpc.hyperlend.finance",
    "https://999.rpc.thirdweb.com",
)
CHAIN_ID = 999
META_NAME = "papertrade-runtime-deployment"
LOG_SPAN = 1000  # rpc.hyperliquid.xyz rejects eth_getLogs ranges above 1000 blocks
LOG_PACE_SECONDS = 0.25  # spacing between chunked eth_getLogs calls
RPC_ATTEMPTS = 15
SCAN_LAG_BLOCKS = 15  # endpoints can trail each other; never scan past head - lag
EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
ZERO_TOPIC = "0x" + "00" * 32
PROBE_ADDRESS = "0x1111111111111111111111111111111111111111"

# Mint curve and fee defaults from the official docs (research/mint-basis.md).
FLAT_RATE = 100.0
FLAT_THRESHOLD_USD = 2_000_000
TAIL_SCALE_USD = 120_000_000
STAKER_CAP_USD = 5_000_000
LOSS_FEE = 0.02
DEFAULT_KEPT = 0.886  # Sumcap's Rollbit-parameter estimate for a 1% move; measure it in the test phase.
QUEUE_STOP_SECONDS = 24 * 3600

# Getters named in the docs, probed when no verified ABI is available.
DOC_GETTERS = {
    "trackedLpUsd": "int256",
    "tailProgressUsd": "uint256",
    "sideBucket": "uint256",
    "tradingPaused": "bool",
}
QUEUE_NAME = re.compile(r"queue|debt|sidebucket", re.I)
PAUSE_NAME = re.compile(r"paused", re.I)


def mint_rate(tracked_lp_usd: float, tail_progress_usd: float | None) -> float:
    """PAPER minted per $1 of eligible loss basis: flat below the threshold, then 100·(S/(S+H))²."""
    if tracked_lp_usd < FLAT_THRESHOLD_USD:
        return FLAT_RATE
    tail = tail_progress_usd if tail_progress_usd is not None else tracked_lp_usd - FLAT_THRESHOLD_USD
    return FLAT_RATE * (TAIL_SCALE_USD / (TAIL_SCALE_USD + max(tail, 0.0))) ** 2


def pair_cost_per_paper(rate: float, kept: float = DEFAULT_KEPT) -> float:
    """USD cost per PAPER of a long/short pair closed at a ±move: the winner's haircut over the loser's mint."""
    return (1 - kept) / ((1 - LOSS_FEE) * rate)


def parse_deployment(text: str) -> dict:
    """Decode the app's runtime deployment metadata from page HTML or a raw base64 payload."""
    text = text.strip()
    for tag in re.findall(r"<meta\b[^>]*>", text, re.I):
        if re.search(rf"""name\s*=\s*["']{META_NAME}["']""", tag, re.I):
            found = re.search(r"""content\s*=\s*["']([^"']*)["']""", tag, re.I)
            if not found:
                raise ValueError(f"{META_NAME} meta tag has no content")
            text = html.unescape(found.group(1)).strip()
            break
    else:
        if "<" in text:
            raise ValueError(f"no {META_NAME} meta tag in the page")
    meta = json.loads(base64.b64decode(text, validate=True).decode("utf-8"))
    if meta.get("schemaVersion") != 1:
        raise ValueError(f"unsupported schemaVersion {meta.get('schemaVersion')!r}")
    if meta.get("chainId") != CHAIN_ID:
        raise ValueError(f"chainId {meta.get('chainId')!r} is not HyperEVM mainnet ({CHAIN_ID})")
    contracts = {k: _address(meta["contracts"][k], k) for k in ("exchange", "paper", "paperStaking", "depositProxyFactory")}
    collateral = meta["collateral"]
    return {
        "chainId": CHAIN_ID,
        "networkProfile": meta.get("networkProfile"),
        "contracts": contracts,
        "collateral": {
            "address": _address(collateral["address"], "collateral"),
            "evmDecimals": int(collateral["evmDecimals"]),
            "coreDecimals": int(collateral["coreDecimals"]),
        },
        "instruments": [{"id": i["id"], "name": i["name"], "assetIndex": i["assetIndex"]} for i in meta["instruments"]],
    }


def fetch_via_wayback(url: str) -> str:
    """Capture `url` with Save Page Now and return the archived HTML (papertrade.xyz is blocked on the workstation network)."""
    headers = {"user-agent": "Mozilla/5.0 ptrack/1"}
    with urllib.request.urlopen(urllib.request.Request(f"https://web.archive.org/save/{url}", headers=headers), timeout=180) as resp:
        resp.read()
    with urllib.request.urlopen(urllib.request.Request(f"https://web.archive.org/web/{time.strftime('%Y%m%d%H%M%S', time.gmtime())}id_/{url}", headers=headers), timeout=120) as resp:
        body = resp.read()
    return (gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body).decode("utf-8")


def _address(value: str, label: str) -> str:
    value = str(value).lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", value) or int(value, 16) == 0:
        raise ValueError(f"{label} address is malformed: {value!r}")
    return value


class Rpc:
    """JSON-RPC client that rotates to the next endpoint on rate limits and network errors."""

    def __init__(self, urls: tuple[str, ...] | None = None):
        override = os.environ.get("PTRACK_RPC")
        self.urls = urls or ((override,) if override else ()) + RPC_URLS
        self.current = 0

    def call(self, method: str, params: list):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        failures = []
        for attempt in range(RPC_ATTEMPTS):
            url = self.urls[self.current]
            try:
                req = urllib.request.Request(url, body, {"content-type": "application/json", "user-agent": "ptrack/1"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    reply = json.load(resp)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                failures.append(f"{url}: {e}")
            else:
                if "error" not in reply:
                    return reply["result"]
                message = reply["error"].get("message", str(reply["error"]))
                if "rate limit" not in message.lower():
                    raise RpcError(message)
                failures.append(f"{url}: {message}")
            self.current = (self.current + 1) % len(self.urls)
            if self.current == 0:
                time.sleep(2 ** min(attempt, 5))
        raise RpcError("all endpoints failed: " + "; ".join(failures[-len(self.urls):]))

    def head(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def block_time(self, number: int) -> int:
        return int(self.call("eth_getBlockByNumber", [hex(number), False])["timestamp"], 16)

    def eth_call(self, to: str, data: bytes) -> bytes | None:
        try:
            out = self.call("eth_call", [{"from": PROBE_ADDRESS, "to": to, "data": "0x" + data.hex()}, "latest"])
        except RpcError:
            return None
        return bytes.fromhex(out[2:]) if out and out != "0x" else None

    def implementation(self, proxy: str) -> str | None:
        slot = self.call("eth_getStorageAt", [proxy, EIP1967_IMPL_SLOT, "latest"])
        impl = "0x" + slot[-40:]
        return impl if int(impl, 16) else None

    def logs(self, address: str, topics: list, start: int, end: int):
        for lo in range(start, end + 1, LOG_SPAN):
            hi = min(lo + LOG_SPAN - 1, end)
            yield from self.call("eth_getLogs", [{"address": address, "topics": topics, "fromBlock": hex(lo), "toBlock": hex(hi)}])
            time.sleep(LOG_PACE_SECONDS)


class RpcError(RuntimeError):
    pass


def selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def read(rpc: Rpc, to: str, signature: str, out_type: str, *args: str):
    data = selector(signature) + b"".join(bytes.fromhex(a[2:].rjust(64, "0")) for a in args)
    raw = rpc.eth_call(to, data)
    return decode([out_type], raw)[0] if raw and len(raw) >= 32 else None


def load_abi(rpc: Rpc, name: str, address: str) -> list | None:
    """Verified ABI for a contract: a dropped-in abi/<name>.json, else Sourcify.

    Behind an EIP-1967 proxy only the implementation's ABI counts; the proxy's own ABI is just upgrade admin.
    """
    local = ABI_DIR / f"{name}.json"
    if local.exists():
        abi = json.loads(local.read_text())
        return abi["abi"] if isinstance(abi, dict) else abi
    target = rpc.implementation(address) or address
    try:
        with urllib.request.urlopen(f"https://sourcify.dev/server/v2/contract/{CHAIN_ID}/{target}?fields=abi", timeout=20) as resp:
            abi = json.load(resp).get("abi")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    if not abi:
        return None
    ABI_DIR.mkdir(exist_ok=True)
    local.write_text(json.dumps(abi, indent=1))
    return abi


def abi_getters(abi: list) -> dict[str, str]:
    """Zero-argument views returning one static scalar — every number worth snapshotting."""
    scalar = re.compile(r"u?int\d*|bool|address")
    return {
        f["name"]: f["outputs"][0]["type"]
        for f in abi
        if f.get("type") == "function"
        and f.get("stateMutability") in ("view", "pure")
        and not f.get("inputs")
        and len(f.get("outputs", [])) == 1
        and scalar.fullmatch(f["outputs"][0]["type"])
    }


def snapshot(rpc: Rpc, dep: dict) -> dict:
    c, coll = dep["contracts"], dep["collateral"]
    usd = 10 ** dep.get("usdDecimals", coll["evmDecimals"])
    paper_dec = read(rpc, c["paper"], "decimals()", "uint8") or 18
    abi = load_abi(rpc, "exchange", c["exchange"])
    getters = abi_getters(abi) if abi else DOC_GETTERS
    values = {}
    for name, out_type in getters.items():
        value = read(rpc, c["exchange"], f"{name}()", out_type)
        if value is not None:
            values[name] = value
    supply = read(rpc, c["paper"], "totalSupply()", "uint256")
    staked = read(rpc, c["paper"], "balanceOf(address)", "uint256", c["paperStaking"])
    cash = read(rpc, coll["address"], "balanceOf(address)", "uint256", c["exchange"])  # n/a if the collateral is a Core deposit bridge, not a token
    block = rpc.head()
    return {
        "block": block,
        "time": rpc.block_time(block),
        "abi": "verified" if abi else "docs-probe",
        "paperSupply": supply / 10 ** paper_dec if supply is not None else None,
        "paperStaked": staked / 10 ** paper_dec if staked is not None else None,
        "cashHeldUsd": cash / 10 ** coll["evmDecimals"] if cash is not None else None,
        "trackedLpUsd": values["trackedLpUsd"] / usd if "trackedLpUsd" in values else None,
        "tailProgressUsd": values["tailProgressUsd"] / usd if "tailProgressUsd" in values else None,
        "queue": {k: v for k, v in values.items() if QUEUE_NAME.search(k) and isinstance(v, int)},
        "paused": any(v for k, v in values.items() if PAUSE_NAME.search(k) and v is True),
        "implementations": {k: rpc.implementation(a) for k, a in c.items()},
        "raw": {k: (str(v) if isinstance(v, int) else v) for k, v in values.items()},
    }


def scan_mints(rpc: Rpc, dep: dict, state: dict, head: int) -> list[dict]:
    start = state.get("mintScanBlock", dep["startBlock"]) + 1
    end = head - SCAN_LAG_BLOCKS
    if start > end:
        return []
    paper_dec = read(rpc, dep["contracts"]["paper"], "decimals()", "uint8") or 18
    mints = [
        {
            "block": int(log["blockNumber"], 16),
            "tx": log["transactionHash"],
            "to": "0x" + log["topics"][2][-40:],
            "paper": int(log["data"], 16) / 10 ** paper_dec,
        }
        for log in rpc.logs(dep["contracts"]["paper"], [TRANSFER_TOPIC, ZERO_TOPIC], start, end)
    ]
    state["mintScanBlock"] = end
    return mints


def gate(snap: dict, state: dict) -> tuple[str, list[str]]:
    """PLAN.md entry gate and stop rules. Returns (GO | WAIT | STOP, reasons)."""
    stops, waits = [], []
    baseline = state.setdefault("implementations", snap["implementations"])
    for name, impl in snap["implementations"].items():
        if baseline.get(name) != impl:
            stops.append(f"{name} implementation changed {baseline.get(name)} -> {impl}: review the upgrade before trading")
    if snap["paused"]:
        stops.append("trading or a market is paused")
    queued = {k: v for k, v in snap["queue"].items() if v}
    if queued:
        since = state.setdefault("queueSince", snap["time"])
        waited = snap["time"] - since
        (stops if waited > QUEUE_STOP_SECONDS else waits).append(f"queue non-empty for {waited / 3600:.1f}h: {queued}")
    else:
        state.pop("queueSince", None)
    lp = snap["trackedLpUsd"]
    if lp is None:
        waits.append("trackedLpUsd unreadable: drop the Exchange ABI into tracker/abi/exchange.json")
    elif lp < STAKER_CAP_USD:
        waits.append(f"pool ${lp:,.0f} below the ${STAKER_CAP_USD:,.0f} entry line")
    if stops:
        return "STOP", stops + waits
    return ("WAIT", waits) if waits else ("GO", ["pool above $5M, queue empty, not paused, contracts unchanged"])


def report(snap: dict, verdict: str, reasons: list[str], new_mints: list[dict], state: dict, wallet: str | None, kept: float) -> str:
    lp, tail = snap["trackedLpUsd"], snap["tailProgressUsd"]
    lines = [f"block {snap['block']}  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(snap['time']))}  abi={snap['abi']}"]
    if lp is not None:
        rate = mint_rate(lp, tail)
        tail_note = "" if tail is not None else " (tail inferred from pool, an upper bound on the rate)"
        lines.append(f"pool ${lp:,.0f}  mint rate {rate:.1f} PAPER/$1{tail_note}  pair cost ${pair_cost_per_paper(rate, kept):.5f}/PAPER at kept={kept}")
    lines.append(f"cash held ${_fmt(snap['cashHeldUsd'])}  PAPER supply {_fmt(snap['paperSupply'])}  staked {_fmt(snap['paperStaked'])}")
    totals = state.setdefault("minted", {"all": 0.0, "wallet": 0.0})
    for m in new_mints:
        totals["all"] += m["paper"]
        if wallet and m["to"] == wallet:
            totals["wallet"] += m["paper"]
    lines.append(f"mints this run {len(new_mints)}  minted since start {totals['all']:,.0f}" + (f"  to wallet {totals['wallet']:,.0f}" if wallet else ""))
    lines.append(f"{verdict}: " + "; ".join(reasons))
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f}"


def run_once(rpc: Rpc, dep: dict, kept: float) -> str:
    DATA.mkdir(exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    snap = snapshot(rpc, dep)
    mints = scan_mints(rpc, dep, state, snap["block"])
    verdict, reasons = gate(snap, state)
    with (DATA / "snapshots.jsonl").open("a") as f:
        f.write(json.dumps({**snap, "verdict": verdict, "reasons": reasons}) + "\n")
    if mints:
        with (DATA / "mints.jsonl").open("a") as f:
            f.writelines(json.dumps(m) + "\n" for m in mints)
    text = report(snap, verdict, reasons, mints, state, dep.get("wallet"), kept)
    STATE.write_text(json.dumps(state, indent=1))
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("deploy", help="save contract addresses from the app page's runtime metadata")
    d.add_argument("source", help="saved page HTML, wayback:<url> to capture the live page via the Wayback Machine, a raw base64 payload, or - for stdin")
    d.add_argument("--wallet", help="your trading wallet, to count PAPER minted to it")
    d.add_argument("--from-block", type=int, help="first block to scan for mints (default: current head)")
    for name in ("snap", "watch"):
        p = sub.add_parser(name)
        p.add_argument("--kept", type=float, default=DEFAULT_KEPT, help="share of a 1%% win kept after the haircut")
        if name == "watch":
            p.add_argument("--every", type=int, default=60, help="seconds between snapshots")
    cv = sub.add_parser("curve", help="mint rate and pair cost per PAPER across pool sizes")
    cv.add_argument("--kept", type=float, default=DEFAULT_KEPT)
    args = ap.parse_args(argv)

    if args.cmd == "curve":
        print(f"{'pool $M':>8} {'PAPER/$1':>9} {'pair $/PAPER':>13} {'1c-loss $/PAPER':>16}")
        for lp_m in (0, 1, 2, 5, 10, 20, 50, 100, 200):
            rate = mint_rate(lp_m * 1e6, None)
            print(f"{lp_m:>8} {rate:>9.1f} {pair_cost_per_paper(rate, args.kept):>13.5f} {1 / ((1 - LOSS_FEE) * rate):>16.5f}")
        return 0

    rpc = Rpc()
    if args.cmd == "deploy":
        if args.source == "-":
            raw = sys.stdin.read()
        elif args.source.startswith("wayback:"):
            raw = fetch_via_wayback(args.source.removeprefix("wayback:"))
        elif Path(args.source).exists():
            raw = Path(args.source).read_text(encoding="utf-8")
        else:
            raw = args.source
        try:
            dep = parse_deployment(raw)
        except ValueError as e:
            print(f"deployment not saved: {e}")
            return 2
        dep["startBlock"] = args.from_block if args.from_block is not None else rpc.head()
        if args.wallet:
            dep["wallet"] = _address(args.wallet, "wallet")
        DEPLOYMENT.write_text(json.dumps(dep, indent=1))
        print(json.dumps(dep["contracts"], indent=1))
        print(f"saved {DEPLOYMENT.name}; mint scan starts at block {dep['startBlock']}")
        return 0

    if not DEPLOYMENT.exists():
        print("no deployment.json yet: run `ptrack.py deploy <saved papertrade.xyz page>` once predeposit opens")
        return 2
    dep = json.loads(DEPLOYMENT.read_text())
    while True:
        print(run_once(rpc, dep, args.kept), flush=True)
        if args.cmd == "snap":
            return 0
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
