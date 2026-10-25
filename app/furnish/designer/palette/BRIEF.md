# Palette from the hero photo (per-batch instructions)

You get one batch file `app/furnish/designer/palette/batches/bNN.json`: a list of products, each with `id`, `name`, `brand`,
`category`, `description`, optional `color_words`/`materials`, and `thumb` (absolute path of a 512 px product photo).
The 3D models of these products are untextured; your job is to say what they look like so the viewer can dress them.

For each product: Read the thumb (one Read call per image, nothing else), look at the product itself (ignore the room,
props and people), and write ONE JSON line to `app/furnish/designer/palette/results/bNN.jsonl`:

{"id":"<id>","parts":[{"part":"<seat|back|cushions|frame|legs|base|top|shade|arm|body|shelves|doors|drawers|mattress|headboard|cord>","finish":"<class>","hex":"#rrggbb"}, ...],"dominant":"#rrggbb","accent":"#rrggbb|null","sheen":"<matte|satin|gloss>","note":"<max 8 words>"}

Rules
- `parts` ordered by how much of the product's visible area each takes (biggest first), 1 to 4 parts. The viewer assigns
  the first finish to the largest mesh part, so get the order right.
- `finish` is exactly one of: fabric, boucle, velvet, leather, wood_light, wood_mid, wood_dark, wood_black, metal_chrome,
  metal_black, metal_brass, metal_white, metal_painted, plastic, glass, glass_opal, marble, stone, concrete, ceramic,
  lacquer, paper, rattan, cork, rubber.
- `hex` is the real colour of that part as seen in the photo, corrected for lighting (a white sofa in warm light is
  still about #f0ece4, not orange). For metals give the metal's colour (#d9d9d9 chrome, #1d1d1d black steel, #c8a24a brass).
- Lamps: the shade or diffuser is usually the biggest part; `glass_opal` for white glass diffusers; the light source is not a part.
- If `color_words` are given and the photo agrees, use them; if the photo shows another variant, trust the photo.
- If the photo is unusable (no product, line drawing, 404 image), write {"id":"<id>","skip":"reason"}.

Mechanics
- Append with a Bash heredoc after EVERY 10 products (so partial work survives): `cat >> results/bNN.jsonl <<'EOF' ... EOF`.
  Before starting, read the results file if it exists and skip ids already present.
- No commentary, no summaries in the file. When all products are done, reply with one line: "bNN: N written, M skipped".
