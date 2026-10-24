# Sunlit: Cal Hacks 13.0 one-pager

Oct 23, 2026 · @Maciej

## Pitch

**Paste a rental listing, see how many hours of direct sun each room gets, every day of the year, before you sign.**

Renters sign 12-month leases from a handful of photos. Those photos never show the bedroom in December at 4pm, the building next door that blocks the sky, or the fog. Light is one of the things people regret most about an apartment and can least check in advance.

Building- and facade-level sun tools already exist (see Competition). None of them knows the inside of the unit: window size, position, room depth. That is the gap.

## Competition and our angle

The core question is solved several times over; our only defensible angle is interior geometry from listing photos, remotely.

| Product | What it does | What it can't do |
| --- | --- | --- |
| [Redfin Sunscore](https://www.redfin.com/news/?p=85478) (Shadowmap, May 2026) | 0 to 100 sun score from exterior 3D geometry | [Not an interior rating](https://theclose.com/redfin-sunscore-is-live-what-agents-should-tell-buyers/): no window size, room depth or unit floor; for-sale listings |
| [Will It Be Bright](https://willitbebright.com/) (Chrome extension, 2026) | Grade on Zillow/Redfin listings from building orientation | Guesses rooms from front/back/left/right; no real geometry |
| [Solis](https://hunted.space/product/solis-home-sun-tracker), Sun Pathway | Room-level sun hours via phone compass | User must be in the apartment |
| [Localize.city](https://probuilder.com/website-allows-new-yorkers-bask-glow) | Per-floor building shading, NYC | Facade level, one city |

**Pitch line:** "Redfin's Sunscore tells you about the building's outside. Even Redfin says it can't tell you about your bedroom. We can, from the listing photos alone."

If listing-photo reconstruction fails, the project collapses into these products. That makes the test below a true go/no-go.

## Product and demo

The user pastes a listing link or address. The app rebuilds the room from the listing photos, places it in the real 3D block around it, and simulates the sun through the year. Output: hours of direct sun per room, by month, with a one-line verdict ("Bedroom: 0 h of direct sun Nov to Feb").

**Two-minute table pitch (judging is table-based, 2 to 3 teams per table):**

1. **Problem, 15 s:** "You're signing a year-long lease from 10 photos. Will the bedroom ever get sun?"
2. **Listing to room, 30 s:** paste a real SF listing. The room builds itself in 3D from its photos, windows marked.
3. **The year in 10 s, 30 s:** shadows of the real neighbouring buildings sweep across the block; winter light (or none) moves across the floor.
4. **The judge's own home, 30 s:** they type their address and pick their window. "Your room gets 1.5 h of sun in December." This is the memorable moment.
5. **Tech, 15 s:** SOTA 3D reconstruction from listing photos, running locally on a laptop, plus real building geometry and solar math.

No voice input: the hall is loud. Keep a 30-second loop running between judges.

## Tech

The SOTA model is necessary, not decoration: it recovers window position and direction that no listing states.

1. **Listing photos to room:** 8 to 15 photos go through a feed-forward 3D reconstruction model ([VGGT](https://github.com/facebookresearch/vggt) or [MapAnything](https://map-anything.github.io), which predicts metric scale), run locally on the Mac via PyTorch `mps`. Output: a point cloud with camera poses.
2. **Room to windows:** detect window regions in the photos, lift them into 3D, and get each window's size, height and facing direction.
3. **Room to world:** geocode the address, match the room's orientation to the street, and load surrounding building footprints and heights.
4. **Sun simulation:** solar position for every daylight hour of the year, ray-cast from each window through neighbouring buildings on the GPU. Optional: weight hours by SF's seasonal fog.
5. **Render:** three.js scene of the block and the room, a year slider, and per-room monthly sun hours.

**Orientation:** reconstruction gives room geometry in its own frame, not compass north. Anchor it with the user picking the facade (street or back) on the 3D block, or by matching the view through the window to surrounding buildings. Interior geometry still comes from the photos, which is the differentiator.

**Fallbacks:** if `mps` fails, use the ASUS Ascent GX10 rental (CUDA) at the event. Pre-compute 3 listings so the demo never depends on a live run. There is no fallback for reconstruction itself: if it fails the test, drop the idea.

## Judging and prize fit

Cal Hacks judges on impact, quality, technical complexity and creativity, and requires a live demo.

| Criterion | Fit | Why |
| --- | --- | --- |
| Impact | Medium-high | Every renter, every lease; a costly, hard-to-check decision |
| Quality | High | Deterministic geometry and solar math; nothing external fails live |
| Technical complexity | High | SOTA 3D reconstruction from photos, geometry, GPU ray casting, 3D rendering |
| Creativity | Medium-high | Room-level light from listing photos is new; building-level shadow maps are not |
| Memorability | High | The judge sees their own room's winter sun |
| Visual | Very high | A year of shadows sweeping a real block in 10 s |

**Prizes to target:** 1st to 3rd Overall, Most Technically Complex Hack, Best Solo Hack, Most Creative Hack, Microsoft "Built for the Real World" (customer understanding, measurable usefulness, path to production, responsible design, end-to-end function). Sponsor-track fit is otherwise thin; don't force one.

## Build plan and risks

**Go/no-go test tonight (time box: 90 min, decide by 23:45):** 5 real SF rental listings (Zillow, Craigslist, Zumper), 6 to 20 photos each, plus your own room photographed listing-style as ground truth.

| Dimension | How to measure | Pass bar |
| --- | --- | --- |
| Reconstruction | VGGT and MapAnything on each listing's photos | Recognizable room in at least 4 of 5 listings |
| Photo registration | Do photos of the same room land in one coherent model? | At least 1 room per listing with 3+ photos registered |
| Window localization | Window found and placed on the right wall in 3D | Correct wall in at least 4 of 5 |
| Metric scale | Door height vs. the standard \~2.0 m | Within ±25% |
| Window size | Compared with a visual estimate from the photos | Within ±30% |
| Orientation anchoring | Facade pick or window-view match vs. the map | Within ±30° of true facing |
| Ground truth | Predicted sun-patch time in your room vs. observed tomorrow morning | Within ±30 min |
| Runtime on Mac | Wall-clock per listing, 15 photos, `mps` | Under 3 min |

**Decision:** go if at least 3 of 5 listings pass reconstruction, window localization and scale. Otherwise switch to hidden events after a quick competition check.

- [ ] **Fri night:** reconstruction test; three.js block with real building footprints and heights; sun position for any hour
- [ ] **Sat morning:** window detection and orientation; ray casting from windows; monthly sun hours per room
- [ ] **Sat afternoon:** listing paste flow, year slider, per-room verdicts; validate against one real room at a known time
- [ ] **Sat night:** pre-compute 3 listings plus the Cal Hacks area; Devpost draft; 30 s demo loop
- [ ] **Sun before 9:00 AM:** submit on Devpost; rehearse the 2-minute pitch 10 times
- [ ] **Sun 10:30 AM to 12:30 PM:** judging at the assigned table

**Risks:**

- **Listing photos too sparse or wide-angle:** pick demo listings with 10+ photos; test on real listings, not your own photos alone.
- **Judge says "Redfin already does this":** lead with the Sunscore comparison and its admitted interior gap.
- **"How accurate is it?":** show the ground-truth test from your own room.
- **Building data gaps:** use the city's open building footprints and heights; check coverage for demo addresses first.
- **Rule:** everything is built from scratch during the event; no code from earlier projects.

## Decision (Oct 23, 22:45): GO

Feasibility test passed with one architecture change: reconstruct per room, not per listing. Full scoreboard and the reasons in [Feasibility test results](Feasibility%20test%20results.md). Friday-night items done: VGGT and MapAnything on `mps`, room clustering by cross-view consistency, SF LiDAR building block in three.js with a sun slider (`app/viewer.html`), year-long ray-cast sun hours per window in 0.6 s on CPU (`app/sunhours.py`).
