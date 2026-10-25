# Login-gated 3D files (owner to fetch)

Brands whose 3D/CAD sit behind a professional login or a bot wall. Nothing here was accessed.

# Login / registration gated 3D (group A)

## Muuto (www.muuto.com)
- Product pages (/product/<Name>/, ~380 in sitemap) show "2D, 3D & Revit files - Download Architect Files here", linking to a Vocast/Presscloud "Digital Showroom": https://download.muuto.com/digitalshowroom/#/product/<id>?tag=<id>  (Angular SPA, REST at download.muuto.com/api/digitalshowroom/1/...). Also "professionals.muuto.com" (Partner Login, /login/?returnUrl=...) for sales tools and pCon catalog (catalog.pcon-solutions.com, third party).
- Formats unknown (page text says 2D, 3D, Revit; sitemap lists pcon/revit/cet/cap planning FAQ). Count unknown (about 380 products). How I know: product page HTML + SPA bundle. Not verified whether the showroom is anonymous: my direct API probe was blocked by the sandbox permission classifier and the browser extension denied reading download.muuto.com, so I stopped. Public site itself only offers Cylindo image viewers (AR pages), no meshes.

## &Tradition (www.andtradition.com)
- Product pages (wp.andtradition.com/wp-json/trouble/post?slug=<slug>&type=products) link "2D/3D Files | Downloads" to andtradition.presscloud.com/selection/<id>. Opening one in a browser shows "This digital showroom is out of service / has been deactivated". Other downloads route via assetslibrary.com (https://www.assetslibrary.com/web/<id>/<slug>/, images and fact sheets PDF; 3D not verified, likely behind the brand asset portal). No public mesh found.

# Group B login notes
No brand in group B gates its 3D files behind a login. Herman Miller and Knoll publish 3D downloads publicly, but only as SketchUp (.skp), AutoCAD 3D (.dwg) and Revit (.rfa zip) files, which the pipeline cannot convert (no mesh formats). See report_herman-miller.json / report_knoll.json.

# Group C - login / registration gated 3D downloads (not accessed; no accounts created)

## Flexform (www.flexform.it)
- Page: https://www.flexform.it/en/architect-designer-resources/3d-quick-download ("Architect & Designer Resources", also "Download 3D Files" on every product page)
- What is behind it: "3D CAD files" per product/composition (formats not visible without login), also hi-res photos, tech sheets. Public product pages only carry a 2D zip (DWG) and PDF data sheet.
- How I know: the site's own JS (Next.js chunk) fetches https://download.flexform.it/3d-files/ with an OAuth bearer header (NextAuth sign-in); an unauthenticated GET returns 401 Authorization Required. Product pages list ~546 products, so roughly that many 3D sets.

## Minotti (www.minotti.com)
- Login / register page: https://www.minotti.com/en/profile (profiles: Minotti Authorized Dealer, Architect, Press)
- What is behind it: "Download Area" (CAD/3D files; product pages say "the CAD files available on our website are copyright-protected"), World of Materials, My Selection. Hi-res images for Press.
- How I know: register text on /en/profile lists Download Area as a benefit of Dealer and Architect accounts; no 3D/CAD links in public product HTML (e.g. /en/hamilton). Formats and counts unknown. (The "captcha" string on the home page is only the reCAPTCHA script tag, not a wall.)

## Cassina (www.cassina.com)
- Product pages (e.g. https://www.cassina.com/ww/en/products/lc9.html) have a "Downloads: Access 2D and 3D drawings, technical sheets... Designed for professionals" accordion; links are class "download-restricted" with data-crm-download="true", pointing to /content/dam/ld/cassina/products/<x>/<sku>/20_area_professionals/... ; those paths are Disallowed in robots.txt and the site has a private-area (professional user type) login (/content/cassina/ww/en/private-area/{user_type}/dashboard.html).
- Formats/counts unknown (login-required). The shop part of the site exposes EUR prices in page JSON (e.g. LC9 Tabouret 990 EUR) but no meshes.

## B&B Italia (www.bebitalia.com)
- Home page returned 403 to the shared helper's request (logged in walls.json); not pursued further. Site is Magento with customer login https://www.bebitalia.com/en-us/customer/account/login/ and a dealers area link https://www.dealersarea.com/Login.aspx. I could not verify what 3D files exist or where.

## Moroso (www.moroso.it) - NOT gated
- https://www.moroso.it/downloads is public: direct links to 3D zips (materiali/3d/*.zip, 3ds), 2D DWG, BIM, product sheets. Used directly (see moroso.py). A "login" link exists in the nav but is not needed.

# Group D: login / gated 3D areas (no accounts created, nothing bypassed)

## Thonet (www.thonet.de)
- Product pages (/en/all-products/detail/<n>) carry no downloads. They link to (a) "Configure CAD model" = pCon.ui web configurator
  (https://ui.pcon-solutions.com/#GATEKEEPER_ID=...&moc=TH&ban=214&cad=true), an interactive JS app (EAI web service backend; export goes through pCon cloud), and
  (b) the media database https://mediendatenbank.thonet.de/en/ (Brandportal SPA): API api/BrandportalData/Albums and /Files/<album> answer 401, so CAD data sits behind a
  portal login/registration (api/Brandportal/Register exists). Only an unauthenticated "Preview" teaser (images) is public. Formats unknown (page says "CAD data"). ~470 product pages listed.
- Login URL: https://mediendatenbank.thonet.de/en/ (registration for architects/planners).

## Audo Copenhagen / Menu (audocph.com)
- Downloads menu points to https://audo.presscloud.com/digitalshowroom/#/gallery/2D-3D-Files (Vocast "Digital Showroom", Angular SPA; label "2D, 3D & Revit Files"; also "Revit & pCon Planner" page).
  The SPA talks to a REST API on presscloud.com with a host-keyed Authorization header; optional login ("enablelogin":1, "enforceLogin":0 on Normann's instance).
  I did not pursue the API (header-keyed calls were judged out of bounds for this task; I got no files). Formats unknown (file-type icons in the SPA include 3ds, skp, stl, zip, igs, 3dm).

## Normann Copenhagen (www.normann-copenhagen.com)
- Plain helper requests to the site worked (curl got the Cloudflare page, python helper did not). Product pages (/en/products/...) link "Downloads: You can download all related files here"
  to https://normann-copenhagen.presscloud.com/digitalshowroom/#/gallery/<product-family> (and "2D/3D CAD Files" gallery Technical-Files-Collections). Same Vocast SPA as Audo; not pursued. ~1300 product pages.

## Ferm Living (fermliving.com)
- Shopify product pages show "Download 2D/3D files" -> https://fermliving.presscloud.com/digitalshowroom/#/gallery/<product> (same Vocast SPA). Not pursued. ~1000 product URLs.

## USM (www.usm.com)
- Public: only a 2D DWG library zip (https://cms.usm.com/media/i5vdhm2o/usm_2d_library_dwg.zip). 3D models are on BIMobject (https://productsite.bimobject.com/en/usm/privatecloud/usm, "Login BIMobjects")
  and pCon.planner ("Login pCon"); the USM Haller configurator exports 2D/3D interactively. Behind login: Revit/BIM, SketchUp, AutoCAD 3D (per the architects page /en/support-for-architects-and-designers).

# Group E: walls and login notes

## Vitra (www.vitra.com) - Cloudflare wall, not a login
- Every plain request to www.vitra.com (sitemap.xml, /en-int/service/download-centre) returns HTTP 403 with the Cloudflare "Just a moment..." challenge page. robots.txt alone is served.
- Download centre URL (public front door): https://www.vitra.com/en-int/service/download-centre (URL is the commonly known download centre; its contents could not be checked).
- Not evaded. Nothing catalogued. Logged in raw/walls.json. Behind the wall: unknown (formats and count could not be determined).
- Reachable only by a human browser session; a manual export would be needed.

# Decisions / not fetched (lead notes)

## Audo Copenhagen (Menu), Normann Copenhagen, Ferm Living
- 2D/3D live in Vocast/Presscloud "digital showrooms" (REST api presscloud.com/api/digitalshowroom/1 with a host-key header, same platform as HAY and Muuto, which were fetched). The agent that probed these was stopped by the permission classifier after its first probes, so they were NOT crawled. Owner decision: allow that API for these hosts (likely several hundred models) or fetch via a browser. Normann/String also answered Cloudflare "Just a moment" on plain curl.

## Flos
- professional.flos.com/en/global/product-downloads/planning-aids/ is public and lists 355 3D zips (OBJ/FBX/3DS/3DM on ctfassets); only the 15 in the first page HTML were fetched. The rest load via a browser-side Algolia search (public key in page); the classifier denied querying it, so ~340 remain. Owner decision.

## Vitra, B&B Italia, Cassina
- Cloudflare / captcha / 403 on plain requests. Not bypassed. 3D files not reachable.

## Herman Miller, Knoll
- Public but only SKP/DWG/RFA (MillerKnoll CAD Pack, cadpack-aws.hermanmiller.com): no mesh format usable, nothing catalogued.

## Thonet, USM
- Thonet: CAD only via pCon.ui or login-gated mediendatenbank.thonet.de. USM: 3D behind BIMobject / pCon.planner logins.
