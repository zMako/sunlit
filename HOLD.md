# HOLD: decisions and actions that need the user (Oct 24, written while the user naps)

1. **Visa "Reimagining Shopping" track.** The Hacker Guide gives criteria only (innovation 25, UX 25, technical 20,
   commerce impact 15, trust and responsibility 15); the Hacker Starter Pack with any Visa API/sandbox is on the Cal Hacks
   live site, which I cannot access. Please check the live site for the Visa starter pack and paste the API/sandbox
   details. Until then the checkout is built against a generic card-sandbox abstraction (payment intent, tokenised test
   card, 3-D Secure step) that can be pointed at Visa's sandbox once we know it.
2. **Coinbase "Best Use of x402".** The guide links a Google Drive doc (view-only link in the PDF); please open it and
   paste the brief. I am building the x402 flow from the public docs (seller endpoint with 402 challenge, buyer agent
   paying in USDC on Base Sepolia through the public facilitator). To run it live you will need: a Coinbase Developer
   Platform account (free) for API keys if we use the CDP facilitator, and a funded Base Sepolia test wallet (faucet).
   I will prepare a local mock facilitator so the demo works offline, with a switch to the real one.
3. **IKEA assets.** Per your direction the catalogue worker downloads IKEA product models/images locally for the demo.
   IKEA's terms restrict copying and embedding their materials; you accepted that risk for a hackathon demo. Nothing is
   re-published beyond your machine.
4. **Anthropic track framing.** The guide's example of a good community is literally "transfer students at Berkeley
   trying to find housing". Our product serves "people moving into an unfurnished SF rental who want it furnished and
   ordered before move-in day". Confirm you want this framing in the submission text.
5. **Other tracks that fit without extra work:** Best Solo Hack (general prize), Creao AI "Best One-Person Company"
   (solo founder; doc link in the PDF needs your login to read). Capital One Nessie (mock banking API) could back the
   budget input with a real "account balance" call if you want a second fintech sponsor; say so.
6. **Google Maps out of the windows:** parked by your instruction until you are back.

## Added by the checkout worker (Oct 24 ~13:30)
7. **x402 goes live only with your CDP account.** Everything runs now against a local mock facilitator (real SDK, real
   EIP-3009 signatures, settlement faked). To settle for real on Base Sepolia: create a CDP API key + wallet secret at
   https://portal.cdp.coinbase.com, export `CDP_API_KEY_ID`, `CDP_API_KEY_SECRET`, `CDP_WALLET_SECRET`, fund the agent
   wallet (address printed by `agent_pay.py`, see app/checkout/README.md) with Base Sepolia USDC + ETH from the CDP
   faucet, restart `app/checkout/server.py`. Per-order real-testnet amount is capped at $1 (X402_REAL_CAP_USD).
8. **Visa track sandbox.** The card rail is a sandbox mock behind one adapter; once the Visa starter pack names its
   sandbox (Cybersource?), the keys needed are: merchant id, REST key id + shared secret, 3-D Secure (Payer Auth) creds.

## Added 15:30 (owner awake)
9. **Microsoft "Grand Prize: Built for the Real World"** fits: a production-minded AI agent in a high-impact domain, judged
   on customer understanding, measurable usefulness, path from prototype to production, responsible design, end-to-end
   functionality. Our angle: the furnishing + checkout agent with budget limits, audit log, human confirmation. Also
   "Microsoft Customer Impact Award" (same criteria). Owner to confirm we enter both.
10. **Creao "Best One-Person Company"**: owner to read the Creao doc (needs login) and confirm.
