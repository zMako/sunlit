"""Local stand-in for the x402 facilitator (verify / settle / supported) so the full HTTP 402 round trip runs with no
Coinbase Developer Platform keys and no testnet funds. Speaks the same JSON contract as the CDP facilitator (x402 v2):
  GET  /supported -> {"kinds":[{"x402Version":2,"scheme":"exact","network":"eip155:84532"}], "extensions":[], "signers":{}}
  POST /verify    {x402Version, paymentPayload, paymentRequirements} -> {"isValid": true, "payer": "0x.."}
  POST /settle    same body -> {"success": true, "transaction": "0x..", "network": "eip155:84532", "payer": "0x..", "amount": ".."}
It checks the EIP-3009 authorization fields are present and that the amount/payee match the requirements, and derives a
deterministic fake transaction hash. Run: feasibility/.venv/bin/python app/checkout/mock_facilitator.py  (port 8767)"""
import hashlib, json, time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

NETWORK = "eip155:84532"   # Base Sepolia
app = FastAPI(title="mock x402 facilitator")
LEDGER = []

@app.get("/supported")
def supported():
    return {"kinds": [{"x402Version": 2, "scheme": "exact", "network": NETWORK, "extra": {"assetTransferMethod": "eip3009"}},
                      {"x402Version": 1, "scheme": "exact", "network": "base-sepolia"}], "extensions": [], "signers": {"eip155": ["0x000000000000000000000000000000000000fAC1"]}}

def _check(body):
    pl, req = body.get("paymentPayload", {}), body.get("paymentRequirements", {})
    inner = pl.get("payload", {}); auth = inner.get("authorization", {})
    payer = auth.get("from"); to = auth.get("to"); value = str(auth.get("value", ""))
    if not (payer and to and inner.get("signature")): return None, "missing_authorization_fields"
    if req.get("payTo") and to.lower() != str(req["payTo"]).lower(): return None, "recipient_mismatch"
    want = str(req.get("amount") or req.get("maxAmountRequired") or "")
    if want and value and int(value) < int(want): return None, "insufficient_amount"
    return {"payer": payer, "to": to, "value": value, "network": pl.get("network") or req.get("network")}, None

@app.post("/verify")
async def verify(request: Request):
    body = await request.json(); info, err = _check(body)
    if err: return JSONResponse({"isValid": False, "invalidReason": err, "invalidMessage": err.replace("_", " ")})
    return {"isValid": True, "payer": info["payer"]}

@app.post("/settle")
async def settle(request: Request):
    body = await request.json(); info, err = _check(body)
    if err: return JSONResponse({"success": False, "errorReason": err, "errorMessage": err.replace("_", " "), "network": NETWORK})
    tx = "0x" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    LEDGER.append({"t": time.time(), "tx": tx, **info}); return {"success": True, "transaction": tx, "network": info["network"] or NETWORK, "payer": info["payer"], "amount": info["value"]}

@app.get("/ledger")
def ledger(): return LEDGER

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8767, log_level="warning")
