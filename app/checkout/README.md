# Sunlit checkout (agentic, two payment rails)

The furnishing agent's items for one or more rooms become an order. A visible agent run (server-sent events) checks stock,
plans delivery and assembly before the move-in date, enforces the user's budget, creates the order and pays.

## Run
```
feasibility/.venv/bin/python app/checkout/mock_facilitator.py   # :8767, x402 facilitator stand-in (verify / settle / supported)
feasibility/.venv/bin/python app/checkout/server.py             # :8766, checkout API + x402-protected merchant endpoint
open http://127.0.0.1:8765/checkout/checkout.html?rooms=gs-22612_plan_03__r0,gs-22612_plan_03__r2&budget=4000&movein=2026-11-15
```
(The page is served by the existing static proxy on :8765; it calls :8766 over CORS.)

## What is real and what is mocked
| piece | status |
|---|---|
| cart from the furnishing plans (`app/furnish/plans/<room>.json`), prices, product links, images | real |
| budget enforcement (lowest-priority, most expensive items dropped first; agent cannot exceed) | real logic |
| stock check, lead times, delivery/assembly slots, carrier | mocked (deterministic per item) |
| order persistence `app/checkout/orders/<id>.json`, receipt, audit log of every agent step | real |
| **card rail**: intent -> tokenised test card 4242… -> 3-D Secure -> authorization -> STOP -> human "Confirm purchase" -> capture | sandbox mock behind `card_rail.SandboxCardAdapter`; no PAN stored; the stop-before-capture is enforced server-side |
| **x402 rail**: merchant `POST /merchant/order/{id}` protected by the official `x402` SDK (FastAPI middleware, scheme `exact`, USDC on Base Sepolia `eip155:84532`); the agent wallet (`agent_pay.py`, eth-account key in `.wallets.json`) pays the 402 with a real EIP-3009 `TransferWithAuthorization` signature via `x402HttpxClient`; spend control `max_amount_per_payment` = the user's budget | protocol real end to end; **settlement mocked** by `mock_facilitator.py` (deterministic tx hash, nothing broadcast) until CDP keys exist |

## Switching x402 to the real Coinbase facilitator (what the user must do)
1. Create a Coinbase Developer Platform account and an API key: https://portal.cdp.coinbase.com -> API keys. Also create a
   wallet secret. Export `CDP_API_KEY_ID`, `CDP_API_KEY_SECRET`, `CDP_WALLET_SECRET` in the shell that runs `server.py`.
2. Fund the agent wallet with testnet USDC: print the buyer address with
   `feasibility/.venv/bin/python -c "import sys; sys.path.insert(0,'app/checkout'); import agent_pay; print(agent_pay.buyer_account().address)"`
   and request Base Sepolia USDC + ETH from the CDP faucet (https://portal.cdp.coinbase.com/products/faucet) or in code
   `cdp.evm.request_faucet(address=..., network="base-sepolia", token="usdc")`.
3. Start `server.py` with the keys set; it uses `cdp.x402.create_facilitator_config()` (CDP facilitator) instead of
   `X402_FACILITATOR_URL`. With a real facilitator the per-order x402 amount is capped by `X402_REAL_CAP_USD` (default
   $1.00) because faucet funds are small; the full total still goes through the card rail. The tx link then points to a
   real Base Sepolia transaction.
Alternatively point `X402_FACILITATOR_URL` at any x402 facilitator that accepts `eip155:84532` without auth.

## Switching the card rail to Visa / Cybersource sandbox
Implement a class with `create_intent / tokenise / authenticate_3ds / authorize / capture` (see `card_rail.py`) and select it
with `CARD_ADAPTER=visa`. Needed from the sandbox: merchant id, REST API key id + shared secret (HTTP-signature auth), Payer
Authentication (3-D Secure) credentials; optionally network tokenisation credentials. Test PANs only. The flow keeps the
human confirmation before capture regardless of adapter.

## Endpoints (:8766)
`GET /cart?rooms=` · `GET /agent/run?rooms=&budget=&movein=&rail=card|x402&exclude=` (SSE) · `POST /merchant/order/{id}` (x402) ·
`POST /order/{id}/confirm` · `GET /order/{id}` · `GET /orders` · `GET /health`

## Trust & responsibility notes (Visa criterion)
Budget is a hard spending limit on the agent and the wallet's SDK spend control; every action is logged and shown live;
explicit human confirmation before any capture; test card numbers only, no PAN stored (token + last4 + brand); the x402
wallet is a dedicated agent wallet with a per-payment cap; order data stays local.
