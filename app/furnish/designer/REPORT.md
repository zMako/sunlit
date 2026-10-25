# Designer tier (catalog_designer): report

Items with models: **3392** across 14 brands. Models: `models/` (rescaled to metres, Y-up, floor at 0), `models_opt/` (gltf-transform Draco + WebP 1024).
Conversion: OBJ/PLY/STL via trimesh; FBX/3DS/DAE via headless Blender 5.2 (/Applications/Blender.app, `blender -b -P blender_convert.py`; bpy pip not needed). Scale/orientation auto-fit to listed dims (common.fit_transform).

| brand | items | formats | price coverage | models before | models after | how 3D is exposed |
|---|---|---|---|---|---|---|
| HAY | 901 | OBJ 901 | 28/901 | 1579 MB | 121 MB | Public Vocast Digital Showroom hay.presscloud.com (iframe on hay.com/professionals/downloads); site's own front-end API with host-key header, no login; 139 '3D files' zips (OBJ/FBX/3DS/DWG/SKP) |
| Muuto | 763 | OBJ 763 | 7/763 | 983 MB | 77 MB | Public Vocast Digital Showroom download.muuto.com (linked from every muuto.com product page as '2D, 3D & Revit files'; enforceLogin=0); 169 3D zips with OBJ+3DS+DWG+SKP per variant |
| Moroso | 423 | 3ds 333, fbx 89, obj 1 | 0/423 | 655 MB | 30 MB | Public https://www.moroso.it/downloads page lists direct links to materiali/3d/*.zip (3DS inside) and .3ds; no login. Product pages via prodotti sitemap. |
| Poliform | 259 | fbx 259 | 0/259 | 646 MB | 21 MB | Product pages embed public s3.poliform.it file URLs (data-file-url: FBX/OBJ/3DM/MAX/SKP/DWG) in the Downloads tab; UI wraps them in a lead-form modal, no login needed for the URLs. FBX holds several size/finish variants laid out side by side; split by footprint clustering. |
| Fritz Hansen | 258 | OBJ 254, FBX 4 | 9/258 | 567 MB | 20 MB | Public Asset Bank downloads.fritzhansen.com; anonymous 'Download original' POST flow (no login); OBJ/FBX/3DS per product |
| Artemide | 213 | 3ds 213 | 0/213 | 354 MB | 7 MB |  |
| Carl Hansen & Son | 130 | obj 127, 3ds 3 | 123/130 | 416 MB | 16 MB | Specs.OtherAssets in each product page's __NEXT_DATA__ links public *_3D*.zip on admincms.carlhansen.com (obj+3ds+dwg+max); prices from de-de market pages |
| Hem | 121 | obj 104, fbx 17 | 121/121 | 982 MB | 31 MB | Each product page lists 'Downloads > 3D files' -> go.hem.com/3d-files/<slug> (301 to storage.googleapis.com/hem-digital-assets, public zips with FBX+RFA+DWG) |
| Louis Poulsen | 111 | fbx 111 | 109/111 | 3354 MB | 100 MB | Public Download Center JSON API (commerce.louispoulsen.com/api/downloadcenter/list?type=fbx + /download), per-variant FBX, no login (also revit/ifc/dxf types) |
| GUBI | 73 | 3ds 73 | 73/73 | 303 MB | 7 MB | product page data lists product-documents/shared/3D Drawings/*.zip, served publicly from media.gubi.com (dwg + 3ds/obj) |
| String | 65 | 3ds 63, obj 2 | 7/65 | 47 MB | 1 MB | Public product-group pages /professionals/3d-images link to anonymous Mediaflow share links (shareapi.mediaflow.com token = share id) and iCatServer transfer links; each zip holds 3DS(+3ds Max, DWG, textures) or OBJ/FBX |
| Artek | 40 | fbx 40 | 37/40 | 23 MB | 5 MB | Public per-product Downloads accordion on artek.fi product pages: <Product>_fbx-<id>.zip and _dae zips (also skp, 3D dxf, rfa, ifc), no login |
| Tom Dixon | 28 | stl 28 | 28/28 | 200 MB | 2 MB |  |
| Flos | 7 | obj 7 | 6/7 | 60 MB | 2 MB |  |

Total models: 10169 MB original -> 440 MB optimised.

## Per-brand notes

### &Tradition
- listed 0, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: False
- see raw/login_A.md

### Artek
- listed 145, with 3D 49, converted 40, items 40; dim mismatches rejected: 9; walled: False; login-gated: False
- dim mismatch pendant-light-a330s-golden-bell: listed max 2.5 model [0.163, 0.163, 1.09]; dim mismatch pendant-light-a331-beehive: listed max 2.5 model [0.33, 0.33, 1.101]; dim mismatch pendant-light-a110-hand-grenade: listed max 2.5 model [0.15, 0.15, 1.3]; dim mismatch kaari-table-round: listed max 1.1 model [0.8, 0.8, 0.74]; dim mismatch aalto-table-rectangular: listed max 2.4 model [1.0, 0.6, 0.74]; dim mismatch aalto-table-square: listed max 1.2 model [0.6, 0.6, 0.74]; dim mismatch screen-100: listed max 2.0 model [1.17, 0.515, 1.0]; dim mismatch pendant-light-a440: listed max 2.0 model [0.189, 0.189, 1.139]; dim mismatch riihitie-plant-pot-b: listed max 0.28 model [0.187, 0.158, 0.119]

### Audo Copenhagen / Menu
- listed None, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: False
- See raw/login_D.md

### B&B Italia
- listed None, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: True; login-gated: False
- home 403 to helper request; not pursued

### Carl Hansen & Son
- listed 446, with 3D 134, converted 130, items 130; dim mismatches rejected: 0; walled: False; login-gated: False
- no listed dims on pages (dimension drawings are images): dims taken from GLB bbox with unit heuristic, unverified. Price = first variant EUR.

### Cassina
- listed None, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: True
- 3D/2D in 20_area_professionals, class download-restricted, robots-disallowed, private-area login; home is now 200

### Ferm Living
- listed 1000, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: False
- See raw/login_D.md

### Flexform
- listed None, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: True
- 3D CAD behind OAuth login (download.flexform.it/3d-files/ -> 401); public product pages only give 2D zip + PDF

### Fritz Hansen
- listed 1428, with 3D 308, converted 308, items 308; dim mismatches rejected: 0; walled: False; login-gated: False
- No web shop (buy_url = store locator); designer/year from asset description; dims from model bbox.

### GUBI
- listed 337, with 3D 109, converted 73, items 73; dim mismatches rejected: 30; walled: False; login-gated: False
- prices: US webshop USD excl. VAT

### HAY
- listed 1413, with 3D 906, converted 901, items 901; dim mismatches rejected: 0; walled: False; login-gated: False
- OBJ used. hay.com shows no prices; US shop is DWR (us.hay.com redirects to dwr.com), prices via DWR index. Dims from model bbox (no listed dims). Some component meshes (modules/parts) flagged by merge.

### Hem
- listed 1481, with 3D 142, converted 121, items 121; dim mismatches rejected: 11; walled: False; login-gated: False
- palo-block-3-seater-low-back: zip >300MB skipped; palo-block-2-seater-high-back: zip >300MB skipped; palo-block-3-seater-medium-back: zip >300MB skipped; palo-block-3-seater-high-back: zip >300MB skipped; palo-block-2-seater-medium-back: zip >300MB skipped; palo-block-2-seater-low-back: zip >300MB skipped; hai-chair-ottoman-set: no glb/obj/fbx/3ds (rfa/dwg only); touchwood-chair: no glb/obj/fbx/3ds (rfa/dwg only); touchwood-armchair: no glb/obj/fbx/3ds (rfa/dwg only); touchwood-counter-chair: no glb/obj/fbx/3ds (rfa/dwg only); bullnose: no glb/obj/fbx/3ds (rfa/dwg only); dsg-hem-toto-table-lamp-small: Hem_Toto_S_Table_Light_3D.obj dims [0.23, 0.264, 1.17] vs listed (0.239, 0.239, 0.279) rejected; dsg-hem-toto-table-lamp-small: Hem_Toto_S_Table_Light_3D.fbx dims [0.23, 1.17, 0.264] vs listed (0.239, 0.239, 0.279) rejected; dsg-hem-knuckle-linear-chandelier: Knuckle_Linear_Chandelier_3D.obj dims [0.721, 1.35, 0.958] vs listed (1.349, 0.45, 0.15) rejected; dsg-hem-knuckle-linear-chandelier: Knuckle_Linear_Chandelier_3D.fbx dims [0.721, 1.35, 0.958] vs listed (1.349, 0.45, 0.15) rejected; experiment-lounge-chair: no glb/obj/fbx/3ds (rfa/dwg only); dsg-hem-alphabeta-pendant: Hem_Alphabeta_Wall_Light_Shades_3D.obj dims [1.878, 0.334, 0.207] vs listed (0.34, 0.34, 0.305) rejected; dsg-hem-alphabeta-pendant: Hem_Alphabeta_Pendant_3D.obj dims [0.336, 1.403, 0.336] vs listed (0.34, 0.34, 0.305) rejected; dsg-hem-alphabeta-pendant: Hem_Alphabeta_Shades_3D.fbx dims [1.878, 0.334, 0.207] vs listed (0.34, 0.34, 0.305) rejected; dsg-hem-toto-table-lamp-medium: Hem_Toto_M_Table_Light_3D.obj dims [0.4, 0.454, 1.249] vs listed (0.409, 0.409, 0.47) rejected; dsg-hem-toto-table-lamp-medium: Hem_Toto_M_Table_Light_3D.fbx dims [0.4, 1.249, 0.454] vs listed (0.409, 0.409, 0.47) rejected; dsg-hem-toto-table-lamp-large: Hem_Toto_L_Table_Light_3D.obj dims [0.562, 1.336, 0.653] vs listed (0.559, 0.559, 0.64) rejected; dsg-hem-toto-table-lamp-large: Hem_Toto_L_Table_Light_3D.fbx dims [0.562, 1.336, 0.653] vs listed (0.559, 0.559, 0.64) rejected; alle-coffee-table-set: no glb/obj/fbx/3ds (rfa/dwg only); udon-chair: no glb/obj/fbx/3ds (rfa/dwg only); dsg-hem-dusk-lamp-large: Hem_DuskLamp_Large_3D.obj dims [0.313, 0.313, 0.77] vs listed (0.31, 0.31, 0.269) rejected; dsg-hem-dusk-lamp-large: Hem_DuskLamp_Large_3D.FBX dims [0.313, 0.313, 0.77] vs listed (0.31, 0.31, 0.269) rejected; dsg-hem-coco-pendant-light: Coco_Pendant_Light_Large_3D.obj dims [0.387, 0.387, 2.416] vs listed (0.399, 0.399, 0.49) rejected; dsg-hem-coco-pendant-light: Coco_Pendant_Light_Medium_3D.obj dims [0.296, 0.296, 2.321] vs listed (0.399, 0.399, 0.49) rejected; dsg-hem-coco-pendant-light: Coco_Pendant_Light_small_3D.obj dims [0.5, 0.502, 5.643] vs listed (0.399, 0.399, 0.49) rejected; dsg-hem-coco-pendant-light: Coco_Pendant_Light_Large_3D.fbx dims [0.387, 0.387, 2.416] vs listed (0.399, 0.399, 0.49) rejected; dsg-hem-knuckle-table-lamp: Knuckle_Table_Light_3D.obj dims [0.572, 0.098, 0.381] vs listed (0.2

### Herman Miller
- listed 1608, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: False
- No convertible mesh format publicly offered; nothing catalogued. Store pages (store.hermanmiller.com) use a JS configurator, no downloadable GLB found.

### Knoll
- listed 577, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: False
- Same MillerKnoll CAD Pack as Herman Miller, no OBJ/FBX/3DS/DAE/GLB; nothing catalogued.

### Louis Poulsen
- listed 222, with 3D 171, converted 111, items 111; dim mismatches rejected: 54; walled: False; login-gated: False
- convert failed 91621-5743155563-01:18538 AJ EKLIPTA 220 33W QT; dim mismatch dsg-louis-poulsen-enigma-pendant-5741088771: listed (0.825, 0.825, None) model [0.825, 0.825, 1.849]; dim mismatch dsg-louis-poulsen-enigma-pendant-5741088768: listed (0.825, 0.825, None) model [0.825, 0.825, 1.849]; dim mismatch dsg-louis-poulsen-lp-grand-suspended-5741091904: listed (0.58, 0.58, 0.16) model [0.579, 0.579, 0.403]; dim mismatch dsg-louis-poulsen-lp-grand-suspended-5741091988: listed (1.48, 1.48, 0.26) model [1.478, 1.478, 0.781]; dim mismatch dsg-louis-poulsen-lp-grand-suspended-5741091962: listed (1.48, 1.48, 0.26) model [1.478, 1.478, 0.781]; dim mismatch dsg-louis-poulsen-lp-grand-suspended-5741091959: listed (0.88, 0.88, 0.2) model [0.879, 0.879, 0.526]; dim mismatch dsg-louis-poulsen-lp-grand-suspended-5741091946: listed (0.88, 0.88, 0.2) model [0.879, 0.879, 0.526]; dim mismatch dsg-louis-poulsen-lp-grand-suspended-5741091933: listed (0.88, 0.88, 0.2) model [0.879, 0.879, 0.526]; dim mismatch dsg-louis-poulsen-lp-grand-suspended-5741091920: listed (0.58, 0.58, 0.16) model [0.579, 0.579, 0.403]; dim mismatch dsg-louis-poulsen-lp-grand-suspended-5741091917: listed (0.58, 0.58, 0.16) model [0.579, 0.579, 0.403]; dim mismatch dsg-louis-poulsen-lp-grand-suspended-5741091975: listed (1.48, 1.48, 0.26) model [1.478, 1.478, 0.781]; convert failed 90295-5741081888-01:18555 PH SNOWBALL 70W E27; dim mismatch dsg-louis-poulsen-aj-table-lamp-5744166409: listed (0.215, 0.215, 0.56) model [0.159, 0.292, 0.546]; dim mismatch dsg-louis-poulsen-aj-table-lamp-5744169435: listed (0.16, 0.215, 0.56) model [0.159, 0.292, 0.546]; dim mismatch dsg-louis-poulsen-aj-table-lamp-5744169516: listed (0.16, 0.215, 0.56) model [0.159, 0.292, 0.546]; dim mismatch dsg-louis-poulsen-aj-50-outdoor-wall-lamp-5743145803: listed (0.349, 0.16, 0.248) model [0.113, 0.338, 0.175]; dim mismatch dsg-louis-poulsen-aj-50-outdoor-wall-lamp-5743145816: listed (0.349, 0.16, 0.248) model [0.113, 0.338, 0.175]; dim mismatch dsg-louis-poulsen-aj-50-outdoor-wall-lamp-5743145829: listed (0.349, 0.16, 0.248) model [0.113, 0.338, 0.175]; convert failed 90193-5743155563-01:18537 AJ EKLIPTA 220 33W QT; convert failed 90193-5743168987-01:18539 AJ EKLIPTA Ø450 LED-DA 3K90 W/GLASS #; dim mismatch dsg-louis-poulsen-aj-wall-lamp-5743150458: listed (0.145, 0.318, 0.18) model [0.178, 0.466, 1.294]; dim mismatch dsg-louis-poulsen-ballerup-mini-5742561349: listed (0.115, 0.115, 0.141) model [0.121, 0.121, 0.093]; dim mismatch dsg-louis-poulsen-basic-mini-5742561365: listed (0.124, 0.124, 0.092) model [0.125, 0.125, 0.046]; download failed 91658-5742561310-01:56268; 56267; download failed 91658-5742561323-01:56272; 56270; dim mismatch dsg-louis-poulsen-lp-circle-semi-recessed-5742587844: listed (0.456, 0.456, 0.156) model [0.457, 0.457, 0.094]; dim mismatch dsg-louis-poulsen-lp-circle-semi-recessed-5742582179: listed (0.456, 0.456, 0.156) model [0.457, 0.457, 0.094]; dim mismatch dsg-louis-poulsen-lp-circle-semi-re

### Minotti
- listed None, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: True
- Download Area needs dealer/architect login; home 'captcha' is just a reCAPTCHA script, not a wall (helper wrongly logged it in walls.json)

### Moroso
- listed 313, with 3D 246, converted 423, items 423; dim mismatches rejected: 0; walled: False; login-gated: False
- no mesh in 2D_Banjooli_tables.zip; no mesh in 2D_Highlands_sofa.zip; no mesh in Yumi_armchair.zip; process failed AR1061.fbx (Moroso_3D_Armada-armchair.zip); process failed FB0T57.fbx (FIshbone____lowtable.zip); process failed FB0T58.fbx (FIshbone____lowtable.zip); implausible dims dsg-moroso-pacific-3d-pacific-pacificlove-sofa-pa1003 [29998.264, 13049.131, 7744.384]; process failed PH00HY.fbx (Phoenix_lowTable.zip); process failed SU0061.fbx (Supernatural_smallarmchair.zip); process failed SU0M66.fbx (Supernatural__chair-1.zip); process failed SU00S1.fbx (Supernatural_table.zip); no mesh in SketchUp_LiloWing_armchair.zip; no mesh in ITA_Tender-Letto.zip; dropped 33 duplicate-dims variants; 3DS parsed with own reader (Blender 5 has no 3ds importer); FBX v6100 unsupported by Blender (7 failed); dims unvalidated (none listed in a machine-readable way); no prices (no web shop)

### Muuto
- listed 380, with 3D 169, converted 763, items 763; dim mismatches rejected: 0; walled: False; login-gated: False
- OBJ used, up to 14 variants per zip; dims from variant folder names (cm) when present. No prices on muuto.com; DWR prices where matched.

### Normann Copenhagen
- listed 1300, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: False
- See raw/login_D.md

### Poliform
- listed 218, with 3D 149, converted 259, items 259; dim mismatches rejected: 0; walled: False; login-gated: False
- blender failed Poliform-ARCA-bed-chart.fbx; blender failed Poliform-CHLOE-bed-chart.fbx; blender failed Poliform-DREAM-bed-chart.fbx; blender failed Poliform-KELLY-bed-chart.fbx; blender failed Poliform-ONDA-bed-chart.fbx; blender failed Poliform-PARK1-bed-chart.fbx; blender failed Poliform-REVER-bed-chart.fbx; dims measured from FBX (page lists none); FBX in files often holds several variants (up to 3 kept per file); some FBX product names differ from the page; no web shop, buy_url=monobrand stores, no prices

### String
- listed 39, with 3D 75, converted 65, items 65; dim mismatches rejected: 2; walled: False; login-gated: False
- dsg-string-free-standing-shelf-galvanized-su-11-1: dropped (part/oversize [3.546, 0.035, 1.272]); dsg-string-free-standing-shelf-galvanized-sbp-11-1: rejected dims [0.591, 0.007, 0.36] vs listed (0.58, 0.005, 0.36); dsg-string-free-standing-shelf-galvanized-free-standing-outdoor: dropped (part/oversize [3.816, 0.333, 1.441]); dsg-string-hooks-mks-10-5: rejected dims [0.042, 0.003, 0.042] vs listed (0.05, 0.01, 0.05); Museum Collection museum_models_max2020_2024-12-12: no obj/fbx/3ds (only max/dwg); dsg-string-pira-pira-parts-2023-02-13-v2: dropped (part/oversize [0.361, 3.547, 2.194]); dsg-string-pira-magazine-shelf-pira-magazine-shelf: dropped (part/oversize [3.25, 3.322, 2.823]); Relief Relief_models_2024-12-12_max2020: no obj/fbx/3ds (only max/dwg)

### Thonet
- listed 470, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: True
- See raw/login_D.md

### USM
- listed None, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: False; login-gated: True
- See raw/login_D.md

### Vitra
- listed 0, with 3D 0, converted 0, items 0; dim mismatches rejected: 0; walled: True; login-gated: False
- Checked robots.txt (ok), sitemap.xml and /en-int/service/download-centre once each: 403 Just a moment. Not evaded. See login_E.md

## Categories
armchair 315, bar_stool 78, bed 26, bench 67, bookcase 120, coffee_table 174, desk 43, desk_chair 32, dining_chair 287, dining_table 448, dresser 53, floor_lamp 58, mirror 22, nightstand 18, other 551, ottoman 103, pendant_lamp 277, plant_pot 5, rug 4, side_table 33, sofa 467, stool 62, table_lamp 140, wardrobe 9

## Dimensions check
Items with listed dims: 1164; height differs >35% from model bbox: 107; items using bbox dims only: 2228.

## Bot walls hit (not bypassed)

- www.vitra.com: HTTP 403 at https://www.vitra.com/sitemap.xml
- www.bebitalia.com: HTTP 403 at https://www.bebitalia.com/
