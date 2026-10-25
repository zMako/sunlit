# Move-in: furnish your next apartment before you move in

Cal Hacks 13.0 (Oct 24-25, 2026) project. Working title; the repository is still called `sunlit` after the idea it started
from (sunlight hours per room), which is archived.

**What it does.** Take a real San Francisco rental listing (its floor plan and its photos), rebuild the apartment as a
clean, walkable 3D model, let an AI agent furnish it with real products within the renter's budget, let the renter move
things around or ask the agent for changes, and check out so everything arrives before move-in day. The agent's work is
visible: plans, placements, rejections ("this sofa does not fit through the door"), prices, and a checkout that stops at
the final confirmation.

**How it works, in one paragraph.** The floor plan is the source of truth for geometry: a classical-vision reader extracts
walls, doors, windows and rooms from the raster plan, scales them from printed dimensions (or the VLM's size estimates,
or door widths), and one VLM call names the rooms, places kitchen and bath fixtures and reviews the result. A procedural
three.js builder turns that layout into an apartment: walls with openings, doors with swing, windows with glass and sky,
floors, baseboards, parametric counters and fixtures, PBR materials and sun through the windows. Listing photos are used
only for what photos are good at: which wall is which, window heights, and the materials, matched against a local CC0
texture library (CLIP + colour). Furniture comes from a catalogue of real products with true dimensions and prices; a
placement solver and an agent loop furnish each room within budget, respecting door swings, walking paths and fixtures.
Checkout runs on two rails: a card-sandbox flow that stops before capture, and x402 (USDC on Base Sepolia) for the
agent-to-merchant payment.

## Run it

```
cd app && set -a && . ../.env && set +a && nohup ../feasibility/.venv/bin/python proxy.py 8765 > proxy.log 2>&1 &
open http://127.0.0.1:8765/plan3d/index.html      # units rebuilt from plans -> open 3D / walk / furnish
open http://127.0.0.1:8765/                         # older photo-reconstruction rooms (kept for reference)
```

`.env` holds `ANTHROPIC_API_KEY` (and `GOOGLE_MAPS_API_KEY`, unused for now). Every paid call goes through
`app/spend.py`, a ledger with hard caps (`CAPS`), currently $10 Anthropic / $5 Google; `app/spend.json` is the ledger.
Python environment: `feasibility/.venv` (torch with MPS, open_clip, opencv, shapely, playwright, anthropic). Large data
(listing photos, plan images, texture library, product models, model weights) is not in git; the scripts below
regenerate it.

## Pipeline, start to finish

| step | what | where |
|---|---|---|
| 1 | Listings from landlords' own sites (Greystar: empty-unit photos + plans; RentSFNow: unit photos + sqft) | `feasibility/scrape_greystar.py`, `feasibility/scrape_rentsfnow.py`, `feasibility/filter_listings.py` |
| 2 | Segmentation (Mask2Former ADE20K), room graph (which photos show the same room) | `app/pipeline2/seg.py`, `app/pipeline/roomgraph.py` |
| 3 | Plan reading: printed dimensions + per-wall openings | `app/pipeline2/plan_reader.py` |
| 4 | Photo -> plan room -> facing walls | `app/pipeline2/plan_link.py` |
| 5a | Plan -> learned wall / window / door masks (CubiCasa5K, pretrained, CC BY-NC) + automatic crop to the drawing(s) | `app/plan3d/cubi.py` (`predict`); repo in `feasibility/cubicasa5k_repo/`, weights in `feasibility/weights/` |
| 5 | Plan -> layout JSON (walls, openings, rooms, fixtures, scale); walls from the learned masks on the ink, ink-only fallback (`PLAN_WALLS=ink`) | `app/plan3d/plan_engine.py` (`layout <plan>`), `rebuild.py` (offline rebuild, `--promote`), `room_names.py` (names from plan text), `batch.py`, `sweep.py`, `reindex.py`, `cleanup.py` |
| 5b | Fine-tuning labels: Claude subagents flag the model's mistakes, code snaps them to the ink; 20 held-out test plans; fine-tune + held-out score | `app/plan3d/labels.py`, `app/plan3d/labels/REVIEWER.md`, `app/plan3d/finetune.py`, `finetune_run.sh` |
| 5c | Townhouses: drawings of one plan stacked as levels (aligned, ordered by UP/DN and captions), stairs from tread lines, stairwells, floor/ceiling slabs, open-to-below mezzanines | `app/plan3d/levels.py` |
| 6 | Layout -> per-room JSON for furnishing | `app/plan3d/rooms_export.py` |
| 7 | Photos -> materials, window specs | `app/furnish/matmatch.py`, `app/plan3d/photo_facts.py`, `app/plan3d/materials_assign.py` |
| 8 | Layout -> three.js apartment (dollhouse with level view, walk with gravity / jump / stairs / furniture you can stand on), plan window | `app/plan3d/apartment.html`, `app/plan3d/build.js`, `app/plan3d/walk.js` |
| 9 | Catalogue of real products | `app/furnish/catalog.py` -> `app/furnish/catalog.json` |
| 10 | Furnishing: solver, planner, agent, UI | `app/furnish/place.py`, `plan.py`, `agent.py`, `furnish.js`, `agent.js` |
| 11 | Checkout (card sandbox + x402), move-in scheduling | `app/checkout/` |

Data contracts are in `ARCHITECTURE.md`. The plan of record is `ROADMAP.md`; decisions waiting for the owner are in
`HOLD.md`; the chronological history is `DEVLOG.md`.

## Data policy

- Listings are taken only from sites whose robots.txt allows it and that do not forbid automated access in their terms
  (Greystar, RentSFNow). Apartments.com and Zillow forbid it (Apartments.com serves an "AI agent detected" page);
  AppFolio-hosted listing pages are disallowed too. We do not work around bot walls.
- Only empty units (furniture pixels under 1% by segmentation); staged photos are set aside per photo.
- Textures: CC0 only (ambientCG, Poly Haven). Product data: facts (name, dimensions, price, URL); IKEA models/images are
  cached locally for the demo at the owner's decision (see HOLD.md).
- No real purchases: card checkout stops before capture; x402 runs on testnet.

## Status

See the bottom of `DEVLOG.md` for the latest dated entry and `app/plan3d/review/REPORT.md` for render quality.
