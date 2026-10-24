"""Buyer side of the x402 rail: an agent wallet that pays an HTTP 402 challenge with USDC on Base Sepolia (eip155:84532).
Uses the official `x402` SDK (client + ExactEvmScheme + httpx transport). The wallet is a local eth-account key
(app/checkout/.wallets.json, created on first run) unless CDP keys are configured; with the mock facilitator the signature
is real EIP-3009 but is never broadcast; with the real CDP facilitator the same code settles on chain once the wallet holds
testnet USDC. Also usable standalone:  agent_pay.py <url> [json body]"""
import asyncio, base64, json, os, pathlib, sys
from eth_account import Account
import httpx
from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm.exact.client import ExactEvmScheme

HERE = pathlib.Path(__file__).resolve().parent; WALLETS = HERE / ".wallets.json"
NETWORK = os.environ.get("X402_NETWORK", "eip155:84532")

def wallets():
    if WALLETS.exists(): return json.load(open(WALLETS))
    w = {"buyer": Account.create().key.hex(), "merchant": Account.create().key.hex()}
    json.dump(w, open(WALLETS, "w"), indent=1); os.chmod(WALLETS, 0o600); return w

def buyer_account(): return Account.from_key(os.environ.get("BUYER_PRIVATE_KEY") or wallets()["buyer"])
def merchant_address(): return Account.from_key(os.environ.get("MERCHANT_PRIVATE_KEY") or wallets()["merchant"]).address

def _b64json(s):
    try: return json.loads(base64.b64decode(s + "=" * (-len(s) % 4)).decode())
    except Exception: return s

async def pay(url: str, body: dict | None = None, trace=None, max_usd: float | None = None):
    """POST to a paid endpoint, paying the 402. `max_usd` is the agent wallet's spend control (the user's budget): the SDK refuses
    any requirement above it. Returns (status, response json, trace dict with challenge/header/settlement)."""
    trace = trace if trace is not None else {}
    async with httpx.AsyncClient(timeout=30) as plain:   # 1) unpaid request to capture the challenge for the UI
        r0 = await plain.post(url, json=body or {})
        trace["challenge_status"] = r0.status_code
        hdr = r0.headers.get("PAYMENT-REQUIRED") or r0.headers.get("X-PAYMENT-REQUIRED")
        trace["challenge"] = _b64json(hdr) if hdr else (r0.json() if r0.headers.get("content-type", "").startswith("application/json") else r0.text[:500])
    acct = buyer_account(); client = x402Client().register(NETWORK, ExactEvmScheme(acct))
    client.set_spend_controls({"max_amount_per_payment": f"${max_usd:.2f}"} if max_usd else False); trace["spend_limit_usd"] = max_usd
    captured = {}
    def dump(m): return m.model_dump(by_alias=True) if hasattr(m, "model_dump") else m
    async def on_response(ctx):   # SDK hook: the signed payload the transport sent and the settlement the server returned
        captured["payment_header"] = "PAYMENT-SIGNATURE"; captured["payment"] = dump(ctx.payment_payload); captured["requirements"] = dump(ctx.requirements)
        if ctx.settle_response is not None: captured["settlement_hook"] = dump(ctx.settle_response)
        if ctx.error is not None: captured["error"] = str(ctx.error)
    client.on_payment_response(on_response)
    async with x402HttpxClient(client, timeout=60) as http:   # 2) paid request (the transport retries with the payment header)
        r = await http.post(url, json=body or {})
    trace.update(captured); trace["status"] = r.status_code
    resp_hdr = r.headers.get("PAYMENT-RESPONSE") or r.headers.get("X-PAYMENT-RESPONSE")
    trace["settlement"] = _b64json(resp_hdr) if resp_hdr else None; trace["payer"] = acct.address
    try: data = r.json()
    except Exception: data = {"text": r.text[:500]}
    return r.status_code, data, trace

if __name__ == "__main__":
    url = sys.argv[1]; body = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    st, data, tr = asyncio.run(pay(url, body)); print(json.dumps({"status": st, "data": data, "trace": tr}, indent=1, default=str))
