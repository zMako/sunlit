"""Agentic checkout server (port 8766). The furnishing agent's chosen items become an order; the agent verifies stock, plans
delivery and assembly before the move-in date, enforces the budget, and pays through one of two rails:
  card  : sandbox intent -> token -> 3-D Secure -> authorization, then STOPS; the human must press "Confirm purchase" to capture.
  x402  : the merchant endpoint POST /merchant/order/{id} is x402-protected; the agent wallet pays the HTTP 402 in USDC on
          Base Sepolia (mock facilitator by default, real CDP facilitator when CDP keys exist).
Run: feasibility/.venv/bin/python app/checkout/server.py   (needs mock_facilitator.py on 8767 unless X402_FACILITATOR_URL is set)."""
import asyncio, json, os, pathlib, sys, time, uuid, datetime as dt, random
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn
HERE = pathlib.Path(__file__).resolve().parent; APP = HERE.parent; PLANS = APP / "furnish" / "plans"; ORDERS = HERE / "orders"; ORDERS.mkdir(exist_ok=True)
sys.path.insert(0, str(HERE)); import card_rail, agent_pay
from x402.server import x402ResourceServer
from x402.http.facilitator_client import HTTPFacilitatorClient
from x402.http.facilitator_client_base import FacilitatorConfig
from x402.http.middleware.fastapi import payment_middleware
from x402.http.types import RouteConfig, PaymentOption
from x402.mechanisms.evm.exact.server import ExactEvmScheme as ExactEvmServerScheme

NETWORK = os.environ.get("X402_NETWORK", "eip155:84532")
FAC_URL = os.environ.get("X402_FACILITATOR_URL", "http://127.0.0.1:8767")
REAL_FACILITATOR = bool(os.environ.get("CDP_API_KEY_ID"))
X402_REAL_CAP = float(os.environ.get("X402_REAL_CAP_USD", "1.00"))   # on the real testnet facilitator, pay at most this much per order (faucet funds)
MERCHANT = agent_pay.merchant_address()
EXPLORER = "https://sepolia.basescan.org/tx/"

app = FastAPI(title="Sunlit checkout")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"], allow_methods=["*"], allow_headers=["*"], expose_headers=["*"])

def facilitator_client():
    if REAL_FACILITATOR:
        try:
            from cdp.x402 import create_facilitator_config   # cdp-sdk: signs requests to the CDP facilitator with the API key
            return HTTPFacilitatorClient(create_facilitator_config())
        except Exception as e: print("[checkout] cdp facilitator config failed, using URL:", e)
    return HTTPFacilitatorClient(FacilitatorConfig(url=FAC_URL))
X402 = x402ResourceServer(facilitator_client()).register(NETWORK, ExactEvmServerScheme())
_middlewares = {}

def order_path(oid): return ORDERS / f"{oid}.json"
def load_order(oid): return json.load(open(order_path(oid)))
def save_order(o): json.dump(o, open(order_path(o["id"]), "w"), indent=1, default=str); return o

# ---------------------------------------------------------------- cart ---------------------------------------------------
PRIORITY = {"bed": 0, "sofa": 0, "dining_table": 0, "desk": 0, "nightstand": 1, "dresser": 1, "wardrobe": 1, "tv_bench": 1, "coffee_table": 1, "dining_chair": 1, "desk_chair": 1, "bookcase": 2, "armchair": 2, "rug": 3, "floor_lamp": 3, "other": 3}
def cart(rooms):
    items = []
    for room in rooms:
        p = PLANS / f"{room}.json"
        if not p.exists(): continue
        plan = json.load(open(p))
        for it in plan.get("items", []):
            if it.get("category") == "fixture" or "x" not in it: continue
            items.append({"room": room, "room_label": plan.get("room_type") or room.split("__")[-1], "id": it.get("id"), "name": it.get("name"), "category": it.get("category", "other"), "price_usd": float(it.get("price_usd") or 0), "price_known": it.get("price_usd") is not None, "price_source": it.get("price_source", "listed"), "source": "amazon" if str(it.get("id", "")).startswith("abo-") else "ikea", "search_url": it.get("search_url"), "product_url": it.get("product_url"), "image": it.get("image"), "dims": [it.get("w_m"), it.get("d_m"), it.get("h_m")], "priority": PRIORITY.get(it.get("category", "other"), 3)})
    return items

@app.get("/cart")
def get_cart(rooms: str):
    items = cart([r for r in rooms.split(",") if r]); return {"items": items, "total_usd": round(sum(i["price_usd"] for i in items), 2), "unpriced": sum(1 for i in items if not i.get("price_known", True)), "estimated_usd": round(sum(i["price_usd"] for i in items if i.get("price_source") == "estimated"), 2), "note": "Prices marked est. are our estimates from comparable products; the merchant confirms the final price before capture.", "merchant": MERCHANT, "network": NETWORK, "facilitator": "CDP (real)" if REAL_FACILITATOR else f"mock at {FAC_URL}"}

# ---------------------------------------------------------------- scheduling (mock carrier) ------------------------------
def lead_days(item_id): random.seed(item_id or "x"); return random.choice([2, 3, 3, 4, 5, 7])
def schedule(items, movein):
    mv = dt.date.fromisoformat(movein); today = dt.date.today()
    delivery = mv - dt.timedelta(days=2)
    while delivery.weekday() == 6: delivery -= dt.timedelta(days=1)   # no Sunday deliveries
    assembly = mv - dt.timedelta(days=1)
    late = [i for i in items if today + dt.timedelta(days=lead_days(i["id"])) > delivery]
    return {"delivery_date": delivery.isoformat(), "delivery_window": "09:00-13:00", "carrier": "IKEA home delivery (mock slots)", "assembly_date": assembly.isoformat(), "assembly_window": "10:00-14:00", "assembler": "assembly partner (mock)", "move_in": mv.isoformat(), "items_at_risk": [i["name"] for i in late], "latest_order_by": (delivery - dt.timedelta(days=max((lead_days(i["id"]) for i in items), default=3))).isoformat()}

# ---------------------------------------------------------------- the agent run (SSE) -------------------------------------
def sse(ev, **data): return f"data: {json.dumps({'event': ev, **data}, default=str)}\n\n"

@app.get("/agent/run")
async def agent_run(rooms: str, budget: float, movein: str, rail: str = "card", exclude: str = ""):
    async def gen():
        excl = set(x for x in exclude.split(",") if x); items = [i for i in cart(rooms.split(",")) if i["id"] not in excl]
        oid = "ord_" + uuid.uuid4().hex[:10]; log = []
        def step(ev, **d):
            log.append({"t": time.time(), "event": ev, **{k: v for k, v in d.items() if k != "order"}}); return sse(ev, order_id=oid, **d)
        yield step("start", text=f"Checkout agent started for {len(items)} items in {len(set(i['room'] for i in items))} room(s). Spending limit ${budget:,.0f}, move-in {movein}.", rail=rail)
        await asyncio.sleep(0.4)
        total = sum(i["price_usd"] for i in items)
        yield step("budget", text=f"Cart total ${total:,.2f} vs budget ${budget:,.2f}.", total=round(total, 2), budget=budget)
        dropped = []
        for it in sorted(items, key=lambda i: (-i["priority"], -i["price_usd"])):   # drop lowest-priority, most expensive first
            if total <= budget: break
            items.remove(it); dropped.append(it); total -= it["price_usd"]
            yield step("drop", text=f"Over budget: removing {it['name']} (${it['price_usd']:,.2f}, {it['category'].replace('_', ' ')}).", item=it["id"]); await asyncio.sleep(0.35)
        yield step("budget_ok", text=f"Within budget: ${total:,.2f} of ${budget:,.2f} ({len(items)} items).", total=round(total, 2), dropped=[d["id"] for d in dropped])
        await asyncio.sleep(0.4)
        for it in items:
            yield step("stock", text=f"Stock check {it['name'][:48]}: in stock, ships in {lead_days(it['id'])} days.", item=it["id"], lead_days=lead_days(it["id"])); await asyncio.sleep(0.12)
        sched = schedule(items, movein)
        yield step("schedule", text=f"Delivery booked {sched['delivery_date']} {sched['delivery_window']}, assembly {sched['assembly_date']} {sched['assembly_window']}, move-in {sched['move_in']}." + (f" At risk: {', '.join(sched['items_at_risk'])}." if sched["items_at_risk"] else ""), schedule=sched)
        await asyncio.sleep(0.4)
        order = {"id": oid, "created": time.time(), "rooms": rooms.split(","), "items": items, "dropped": dropped, "total_usd": round(total, 2), "budget_usd": budget, "move_in": movein, "schedule": sched, "rail": rail, "status": "created", "log": log, "merchant": MERCHANT, "network": NETWORK, "privacy": "no card data stored; only tokens, ids and amounts"}
        save_order(order); yield step("order", text=f"Order {oid} created with the merchant ({MERCHANT[:10]}…).")
        await asyncio.sleep(0.3)
        if rail == "card":
            ad = card_rail.adapter(); intent = ad.create_intent(total, "USD", oid, {"movein": movein}); yield step("card_intent", text=f"Payment intent {intent['intent_id']} for ${total:,.2f} ({ad.name}).", intent=intent); await asyncio.sleep(0.3)
            token = ad.tokenise(intent, "4242424242424242", "12/29"); yield step("card_token", text=f"Card tokenised: {token['brand']} •••• {token['last4']} (test card, no PAN stored).", token=token); await asyncio.sleep(0.3)
            a3 = ad.authenticate_3ds(intent, token); yield step("card_3ds", text=f"3-D Secure {a3['3ds_version']}: {'challenge completed' if a3['challenge'] else 'frictionless'}, ECI {a3['eci']}.", auth3ds=a3); await asyncio.sleep(0.4)
            auth = ad.authorize(intent, token, a3); yield step("card_auth", text=f"Authorized ${auth['amount']:,.2f}, approval {auth['approval_code']}. Capture is held for your confirmation.", auth=auth)
            order.update({"status": "awaiting_confirmation", "card": {"intent": intent, "token": {k: v for k, v in token.items() if k != "token"}, "auth": auth}}); save_order(order)
            yield step("await_confirm", text="Stopped before capture. Press Confirm purchase to complete the order.")
        else:
            price = total if not REAL_FACILITATOR else min(total, X402_REAL_CAP)
            yield step("x402_begin", text=f"Paying the merchant endpoint with USDC on {NETWORK} via x402 ({'CDP facilitator' if REAL_FACILITATOR else 'local mock facilitator'}): ${price:,.2f}." + ("" if price == total else f" (real-testnet cap ${X402_REAL_CAP:.2f} of the ${total:,.2f} total)"), price=price)
            order["x402"] = {"price_usd": price}; save_order(order); _middlewares[oid] = (price, None)
            trace = {}
            try:
                status, data, trace = await agent_pay.pay(f"http://127.0.0.1:8766/merchant/order/{oid}", {"order_id": oid}, trace, max_usd=budget)
                yield step("x402_challenge", text=f"Merchant answered HTTP {trace.get('challenge_status')} with payment requirements.", challenge=trace.get("challenge")); await asyncio.sleep(0.3)
                yield step("x402_paid_header", text=f"Agent wallet {trace.get('payer')} signed an EIP-3009 USDC authorization and retried with the {trace.get('payment_header')} header.", payment=trace.get("payment")); await asyncio.sleep(0.3)
                settle = trace.get("settlement") or {}
                tx = settle.get("transaction") if isinstance(settle, dict) else None
                ok = status == 200 and (not isinstance(settle, dict) or settle.get("success", True))
                order.update({"status": "paid_x402" if ok else "x402_failed", "x402": {**order["x402"], "status": status, "settlement": settle, "tx": tx, "explorer": (EXPLORER + tx) if tx else None, "payer": trace.get("payer"), "mock": not REAL_FACILITATOR, "merchant_response": data}}); save_order(order)
                yield step("x402_settled", text=(f"Facilitator verified and settled: tx {tx[:18]}… on {settle.get('network', NETWORK)}" if tx else f"Payment response: HTTP {status}") + (" (mock facilitator: not broadcast)" if not REAL_FACILITATOR else ""), settlement=settle, tx=tx, explorer=(EXPLORER + tx) if tx else None, status=status, ok=ok)
            except Exception as e:
                order.update({"status": "x402_failed", "x402": {**order.get("x402", {}), "error": f"{type(e).__name__}: {e}", "trace": trace}}); save_order(order)
                yield step("x402_error", text=f"x402 payment failed: {type(e).__name__}: {str(e)[:200]}", error=str(e))
        order["log"] = log; save_order(order)
        yield step("done", text="Agent run complete.", order=order)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ---------------------------------------------------------------- merchant: x402-protected order endpoint -----------------
@app.post("/merchant/order/{oid}")
async def merchant_order(oid: str, request: Request):
    if not order_path(oid).exists(): return JSONResponse({"error": "unknown order"}, 404)
    order = load_order(oid); price = (order.get("x402") or {}).get("price_usd") or order["total_usd"]
    mw = _middlewares.get(oid, (None, None))[1]
    if mw is None:
        routes = {f"POST /merchant/order/{oid}": RouteConfig(accepts=[PaymentOption(scheme="exact", pay_to=MERCHANT, price=f"${price:.2f}", network=NETWORK)], description=f"Sunlit order {oid}: {len(order['items'])} items for move-in {order['move_in']}", mime_type="application/json")}
        mw = payment_middleware(routes, X402, sync_facilitator_on_start=True); _middlewares[oid] = (price, mw)
    async def fulfil(req):
        o = load_order(oid); o["merchant_ack"] = {"accepted": True, "order_id": oid, "items": len(o["items"]), "delivery": o["schedule"]["delivery_date"], "t": time.time()}; save_order(o)
        body = json.dumps({"accepted": True, "order_id": oid, "items": len(o["items"]), "delivery_date": o["schedule"]["delivery_date"], "assembly_date": o["schedule"]["assembly_date"]}).encode()
        async def one(): yield body
        return StreamingResponse(one(), media_type="application/json")   # the x402 middleware reads response.body_iterator (Starlette call_next semantics)
    return await mw(request, fulfil)

# ---------------------------------------------------------------- orders -------------------------------------------------
@app.post("/order/{oid}/confirm")
def confirm(oid: str):
    o = load_order(oid)
    if o.get("status") != "awaiting_confirmation": return JSONResponse({"error": f"order is {o.get('status')}"}, 400)
    ad = card_rail.adapter(); cap = ad.capture(o["card"]["intent"], o["card"]["auth"]); o["card"]["capture"] = cap; o["status"] = "paid_card"; o["confirmed_by_human_at"] = time.time(); save_order(o)
    return {"status": o["status"], "capture": cap}

@app.get("/order/{oid}")
def get_order(oid: str):
    if not order_path(oid).exists(): return JSONResponse({"error": "unknown order"}, 404)
    return load_order(oid)

@app.get("/orders")
def orders(): return sorted([{k: o.get(k) for k in ("id", "created", "status", "total_usd", "rail", "move_in")} for o in (json.load(open(p)) for p in ORDERS.glob("ord_*.json"))], key=lambda o: -o["created"])

@app.get("/health")
def health(): return {"ok": True, "merchant": MERCHANT, "network": NETWORK, "facilitator": "cdp" if REAL_FACILITATOR else FAC_URL, "x402_real_cap_usd": X402_REAL_CAP}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")
