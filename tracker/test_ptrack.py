import base64
import json

import pytest

import ptrack

DEPLOYMENT = {
    "schemaVersion": 1,
    "networkProfile": "mainnet",
    "chainId": 999,
    "contracts": {
        "exchange": "0x" + "a1" * 20,
        "paper": "0x" + "b2" * 20,
        "paperStaking": "0x" + "c3" * 20,
        "depositProxyFactory": "0x" + "d4" * 20,
    },
    "collateral": {"address": "0x6b9e773128f453f5c2c60935ee2de2cbc5390a24", "evmDecimals": 6, "coreDecimals": 8},
    "instruments": [{"id": 0, "name": "BTC", "assetIndex": 0, "priceScale": 10}, {"id": 1, "name": "ETH", "assetIndex": 1, "priceScale": 100}],
}
PAYLOAD = base64.b64encode(json.dumps(DEPLOYMENT).encode()).decode()


@pytest.mark.parametrize("lp, expected", [(0, 100.0), (-5e5, 100.0), (1.99e6, 100.0), (10e6, 87.9), (50e6, 51.0), (100e6, 30.3)])
def test_mint_rate_matches_docs_curve(lp, expected):
    assert ptrack.mint_rate(lp, None) == pytest.approx(expected, abs=0.05)


def test_tail_progress_overrides_pool_once_capped():
    # Above the $5M cap the pool stays flat while tail progress keeps growing, so the rate keeps decaying.
    assert ptrack.mint_rate(5e6, 48e6) == pytest.approx(51.0, abs=0.05)


def test_pair_cost_per_paper():
    assert ptrack.pair_cost_per_paper(100, 0.886) == pytest.approx(0.114 / 98)


def test_parse_deployment_from_page_html():
    page = f'<html><head><meta content="{PAYLOAD}" name="papertrade-runtime-deployment"></head></html>'
    dep = ptrack.parse_deployment(page)
    assert dep["contracts"]["exchange"] == "0x" + "a1" * 20
    assert dep["collateral"]["evmDecimals"] == 6
    assert [i["name"] for i in dep["instruments"]] == ["BTC", "ETH"]


def test_parse_deployment_from_raw_base64():
    assert ptrack.parse_deployment(PAYLOAD)["contracts"]["paper"] == "0x" + "b2" * 20


@pytest.mark.parametrize("patch, message", [({"chainId": 998}, "chainId"), ({"schemaVersion": 2}, "schemaVersion")])
def test_parse_deployment_rejects_wrong_network(patch, message):
    bad = base64.b64encode(json.dumps({**DEPLOYMENT, **patch}).encode()).decode()
    with pytest.raises(ValueError, match=message):
        ptrack.parse_deployment(bad)


def test_parse_deployment_rejects_page_without_tag():
    with pytest.raises(ValueError, match="no papertrade-runtime-deployment"):
        ptrack.parse_deployment("<html><head></head></html>")


def snap(**over):
    base = {"time": 1_000_000, "trackedLpUsd": 6e6, "queue": {}, "paused": False, "implementations": {"exchange": "0x01"}}
    return {**base, **over}


def test_gate_go_when_pool_capped_and_queue_empty():
    assert ptrack.gate(snap(), {})[0] == "GO"


def test_gate_waits_below_cap():
    verdict, reasons = ptrack.gate(snap(trackedLpUsd=3e6), {})
    assert verdict == "WAIT" and "below" in reasons[0]


def test_gate_queue_escalates_to_stop_after_24h():
    state = {}
    assert ptrack.gate(snap(queue={"sideBucket": 5}), state)[0] == "WAIT"
    assert ptrack.gate(snap(queue={"sideBucket": 5}, time=1_000_000 + 25 * 3600), state)[0] == "STOP"
    assert ptrack.gate(snap(), state)[0] == "GO" and "queueSince" not in state


def test_gate_stops_on_upgrade_and_pause():
    state = {}
    ptrack.gate(snap(), state)
    assert ptrack.gate(snap(implementations={"exchange": "0x02"}), state)[0] == "STOP"
    assert ptrack.gate(snap(paused=True), {})[0] == "STOP"


def test_abi_getters_keeps_scalar_views_only():
    abi = [
        {"type": "function", "name": "trackedLpUsd", "stateMutability": "view", "inputs": [], "outputs": [{"type": "int256"}]},
        {"type": "function", "name": "positions", "stateMutability": "view", "inputs": [{"type": "uint256"}], "outputs": [{"type": "uint256"}]},
        {"type": "function", "name": "liquidate", "stateMutability": "nonpayable", "inputs": [], "outputs": []},
        {"type": "function", "name": "instruments", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint256[]"}]},
        {"type": "event", "name": "PositionClosed", "inputs": []},
    ]
    assert ptrack.abi_getters(abi) == {"trackedLpUsd": "int256"}


class FakeRpc(ptrack.Rpc):
    def __init__(self, logs):
        self._logs, self.ranges = logs, []

    def eth_call(self, to, data):
        return None

    def logs(self, address, topics, start, end):
        self.ranges.append((start, end))
        return iter(self._logs)


def test_scan_mints_decodes_and_advances_cursor():
    to = "0x" + "e5" * 20
    log = {"blockNumber": hex(120), "transactionHash": "0xabc", "topics": [ptrack.TRANSFER_TOPIC, ptrack.ZERO_TOPIC, "0x" + "0" * 24 + to[2:]], "data": hex(9_800 * 10**18)}
    rpc, state = FakeRpc([log]), {}
    dep = {"contracts": DEPLOYMENT["contracts"], "startBlock": 100}
    head = 150 + ptrack.SCAN_LAG_BLOCKS
    mints = ptrack.scan_mints(rpc, dep, state, head)
    assert mints == [{"block": 120, "tx": "0xabc", "to": to, "paper": 9_800.0}]
    assert rpc.ranges == [(101, 150)] and state["mintScanBlock"] == 150
    assert ptrack.scan_mints(rpc, dep, state, head) == []




def test_rpc_rotates_to_next_endpoint_on_rate_limit(monkeypatch):
    replies = {"a": {"error": {"message": "rate limited"}}, "b": {"result": "0x10"}}
    calls = []

    class Resp:
        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        return Resp(req.full_url)

    monkeypatch.setattr(ptrack.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ptrack.json, "load", lambda resp: replies[resp.url])
    monkeypatch.setattr(ptrack.urllib.request, "Request", lambda url, body, headers: type("R", (), {"full_url": url})())
    rpc = ptrack.Rpc(urls=("a", "b"))
    assert rpc.head() == 16 and calls == ["a", "b"] and rpc.current == 1


def test_rpc_raises_non_rate_limit_errors_immediately(monkeypatch):
    monkeypatch.setattr(ptrack.urllib.request, "Request", lambda url, body, headers: type("R", (), {"full_url": url})())
    monkeypatch.setattr(ptrack.urllib.request, "urlopen", lambda req, timeout: type("C", (), {"__enter__": lambda s: s, "__exit__": lambda s, *e: False})())
    monkeypatch.setattr(ptrack.json, "load", lambda resp: {"error": {"message": "execution reverted"}})
    with pytest.raises(ptrack.RpcError, match="execution reverted"):
        ptrack.Rpc(urls=("a",)).head()


def test_load_abi_ignores_proxy_admin_abi(monkeypatch, tmp_path):
    monkeypatch.setattr(ptrack, "ABI_DIR", tmp_path)
    queried = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(url, timeout):
        queried.append(url)
        return Resp()

    monkeypatch.setattr(ptrack.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ptrack.json, "load", lambda resp: {"abi": None})
    rpc = type("P", (), {"implementation": lambda self, a: "0x" + "77" * 20})()
    assert ptrack.load_abi(rpc, "exchange", "0x" + "a1" * 20) is None
    assert len(queried) == 1 and "77" * 20 in queried[0]
