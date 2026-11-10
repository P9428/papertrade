"""Pins liveleg's EIP-712 encoding to two real mainnet Close intents (HyperEVM tx 0xde30ba04...f1d9, block 48187943):
the signature must recover the registered session key and the intent id must equal the one the relayer recorded."""
import json
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak
import liveleg

SESSION_KEY = "0x267187775a7d539f23a0fdeb673cc61163fbe111"
CLOSES = [
    ({"user": "0x49e96e255ba418d08e66c35b588e2f2f3766e1d0", "positionIds": [3969], "nonce": 1580842831, "deadline": 1791657237},
     28, "0x085663262127fce37fe74a64648221e1508c3f8ca59dbb2dd7dad071cdbd372e", "0x19745cb095da0755b02daab4196116d3520ef2e88167114b73672ede2f27ca89",
     "0x02a1a5609273b3567d6028c4d8c906de22b2bfbee0a59971c9b4660b94df950c"),
    ({"user": "0x49e96e255ba418d08e66c35b588e2f2f3766e1d0", "positionIds": [3912], "nonce": 1580842832, "deadline": 1791657238},
     27, "0xf2bc0f99a5110c476bd74d55e9212c4461ae833397b0ff180b9c061a46245b9c", "0x5392291625f7b0c93bf64f1b7422a71413b3508dee81f3b3975267f24fd622dd",
     "0x98d18aa5597ee213a0942dde0c29aa2fc0008c3e1f3b3e09984684458fec80e7"),
]


def digest_of(primary, message):
    typed = {"types": liveleg.TYPES_WITH_DOMAIN(primary), "primaryType": primary, "domain": liveleg.DOMAIN, "message": message}
    return encode_typed_data(full_message=typed)


def test_mainnet_close_intents_recover_session_key_and_intent_id():
    for message, v, r, s, onchain_id in CLOSES:
        signable = digest_of("Close", message)
        sig = bytes.fromhex(r[2:]) + bytes.fromhex(s[2:]) + bytes([v])
        signer = Account.recover_message(signable, signature=sig).lower()
        assert signer == SESSION_KEY
        from eth_account._utils.signing import hash_of_signed_transaction  # noqa: F401  (import check only)
        from eth_account.messages import _hash_eip191_message
        digest = _hash_eip191_message(signable)
        intent_id = "0x" + keccak(liveleg.INTENT_ID_TAG + digest + bytes.fromhex(signer[2:])).hex()
        assert intent_id == onchain_id


def test_sign_intent_round_trip_and_wire_form():
    acct = Account.create()
    msg = {"user": acct.address.lower(), "instrumentId": 1, "isLong": False, "size": 10**19, "leverage": 50, "useDebt": False, "nonce": 256, "deadline": 1_800_000_000}
    out = liveleg.sign_intent("OpenPosition", msg, acct.key.hex())
    w = out["signed"]
    assert out["action"] == "openPosition" and out["signer"] == acct.address.lower()
    assert w["size"] == "10000000000000000000" and w["leverage"] == "50" and w["isLong"] is False and w["v"] in ("27", "28")
    sig = bytes.fromhex(w["r"][2:]) + bytes.fromhex(w["s"][2:]) + bytes([int(w["v"])])
    assert Account.recover_message(digest_of("OpenPosition", msg), signature=sig).lower() == acct.address.lower()


def test_minimum_unit_from_live_shape():
    state = {"minimumTradeSizeRaw": str(10 * 10**18), "minimumOpenNotionalRaw": str(500 * 10**18), "maximumLeverage": 1000}
    assert liveleg.minimum_unit(state) == (10 * 10**18, 50)
