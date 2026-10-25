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

## Added 18:05
11. **API spend is at $8.89 of the $10 Anthropic cap.** The Sonnet annotation batch ran faster than expected and covered
    68 units (~5 cents each, reader + repair + annotation). Left: ~$1.10, enough for Haiku furnishing/chat runs (0.2 cents
    each) and a handful of annotations (the 777 Tenn demo unit still needs one). Raise the cap if you want more units
    annotated or Sonnet material picks. Subagents run on your Claude Code plan, not on this ledger.
12. **Map front door** (owner's idea, Oct 24 ~17:45): being built in app/map/ (Leaflet + cached OSM tiles, listing cards
    with photos/plans/price/description, detail drawer into 3D/furnish/checkout, compare tray). Scope decision still open:
    keep it as the entry screen, or grow it into a comparison site? Owner wanted to come back to this.

## Added 22:45 (end of the nap work)
13. **Library sources.** AvalonBay was dropped: its terms forbid robots/scrapers. UDR (no terms page, robots allow,
    per-plan sqft) and Greystar's Bay Area properties were added instead: 813 unit types, 58-59 buildings, 134 true size.
    If you know a landlord whose terms allow it and who publishes plans with sqft, that is the cheapest way to more
    true-size units.
14. **Spend $9.07 / $10.** On-demand annotation costs ~7 cents a click; ~13 clicks left before the ledger refuses. Raise
    the cap before the demo if judges will click freely.
15. **Plan-engine bug to fix tomorrow:** gs-20665_plan_00 bedroom (r0) has a jagged south wall with stubs and a toilet
    placed inside it (seen in the side-by-side pair 20665/17). Many new UDR/Bay Area plans read as 13-16 small rooms or
    only a bath; the on-demand annotation warns when rooms cover < half the listed sqft.
16. **Amazon as a second catalogue (owner's ask, 23:10).** Being added from the Amazon Berkeley Objects dataset
    (CC BY-NC 4.0: fine for the hackathon demo, not for a commercial launch without Amazon's agreement): a few hundred
    furniture models with dimensions and ASIN links, no prices. Live prices need the Product Advertising API, which
    requires an Amazon Associates account; if you have or want one, say so and the price field can be filled.
