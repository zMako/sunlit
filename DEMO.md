# Demo script (draft for the owner; 3 minutes, judging Sun Oct 25 10:30-12:30)

## One line
Pick a real SF rental, get its apartment rebuilt in 3D from the floor plan, let an agent furnish it with real products within
your budget, move things around or ask for changes, and order everything so it arrives before move-in day.

## Flow (what is on screen)
1. **The listing** (10 s). plan3d/index.html: a building (1000 Green, 1000 Green St) and its unit types, each with the
   landlord's floor plan. Say: "we only use what the listing publishes: the plan and the photos."
2. **The apartment** (30 s). Open unit 03 as a dollhouse: six rooms, kitchen counters, tub, doors with swing, windows.
   Section slider. Switch to walk mode, stand in the living room, look at the bay windows. Say: "the plan is read by
   classical vision, scaled from the printed dimensions, named by Claude; nothing here is guessed from depth."
3. **Furnish with the agent** (60 s). Budget 3,500, style "warm Scandinavian", press Furnish. Top-down view, items stream
   in one by one with reasons; the agent rejects a sofa that would not fit through the door and picks a smaller one;
   running total against the budget. Drag the coffee table, rotate the armchair. Type "make it cosier, add a reading
   lamp by the window". Camera preset "sofa view", Render.
4. **Checkout** (45 s). checkout.html with the two rooms, budget bar, move-in date. Agent checkout: stock, delivery two
   days before move-in, assembly the day before; card rail authorises and STOPS at Confirm purchase (we never buy);
   switch rail to x402: the 402 challenge, the signed USDC payment, verify/settle, tx link (testnet).
5. **Close** (15 s). "Every listing on this page went through the same pipeline; 25 unit types from four buildings today,
   and the engine reads 370 of the 418 plans we scraped." Tracks: Visa Reimagining Shopping, Coinbase x402, Best Solo
   Hack, Microsoft Built for the Real World (production-minded agent: budget limits, audit log, human confirmation),
   Creao Best One-Person Company, Anthropic track (community: people moving into an unfurnished SF rental).

## Backup
- If the live agent run stalls: Auto-furnish all rooms (deterministic planner) is instant.
- If x402 real facilitator is not configured: the mock facilitator path is the default and looks identical.
- Pre-rendered screenshots: app/plan3d/review/*.png, app/plan3d/test_furnished.png, app/checkout/test_checkout*.png.

## Honest limits to volunteer if asked
Plans in 3D-render style are out of scope; thin closet walls and faint door arcs sometimes mis-read; undimensioned plans
are scaled from Claude's size estimates (±15%); materials are matched, not measured; fixtures are parametric.

## Track one-liners (for the submission form)
- **Visa, Reimagining Shopping.** Shopping that starts from the space, not the catalogue: the agent furnishes a real
  apartment within a budget, every pick explained, every rejection shown, and checkout stops at a human confirmation.
  Trust: budget is a hard limit, full audit log, tokenised test card only, no card data stored.
- **Coinbase, Best Use of x402.** The merchant endpoint is x402-protected; the buyer agent pays the 402 with a signed USDC
  transfer on Base Sepolia, verified and settled by the facilitator, inside the same request flow. Spend cap = budget.
- **Microsoft, Built for the Real World.** A production-minded agent for a real, costly moment (moving in): measurable
  usefulness (fits, budget, delivery before move-in), path to production (plan reader + procedural builder run on every
  listing we scraped), responsible design (limits, logging, confirmation), end to end from listing to order.
- **Anthropic.** Community: people moving into an unfurnished SF rental. Problem: furnishing a place you have never stood
  in. It works on 289 real unit types from 22 buildings; Claude reads plans, names rooms, places fixtures, picks products.
- **Best Solo Hack / Creao One-Person Company.** One person, one weekend, one pipeline from scraped listing to paid order.
