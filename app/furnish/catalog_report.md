# Furniture catalogue report (final)

- Items: 466; with local GLB: 383 (507.2 MB total, avg 1.32 MB); with local image: 466; with image URL: 466; without GLB url: 83

## Per category

- armchair: 25
- bar_stool: 22
- bed: 30
- bookcase: 13
- coffee_table: 29
- desk: 19
- desk_chair: 8
- dining_chair: 31
- dining_table: 30
- dresser: 25
- floor_lamp: 7
- mirror: 9
- nightstand: 27
- plant: 1
- plant_pot: 29
- rug: 32
- side_table: 30
- sofa: 31
- table_lamp: 15
- tv_bench: 36
- wardrobe: 17

## style_tags (all tags / primary tag)

- scandinavian: 397 / 334
- rustic: 174 / 63
- modern: 138 / 20
- minimal: 125 / 27
- classic: 43 / 8
- industrial: 20 / 6
- mid-century: 14 / 8

Tags are keyword-inferred from name/description/colour/type; items with no cue default to `scandinavian` (IKEA house style), so treat that tag as weak.

## Failures (0 asset downloads this run)


## Notes

- Category pages ignore `?page=N` server-side (JS pagination), so breadth comes from several sub-category pages per category (~60 pages); each yields 20-100 links. Thin categories (nightstand, dresser, wardrobe, plant, plant_pot) are limited by what IKEA US lists and by dimension/price filters (items without width/depth/height or price are dropped).
- At most 4 colourways of one series per category; other colourways are in `variants` (product URLs).
- Rugs without a height get 0.015 m.
- Files: `models/<id>.glb`, `imgcache/<id>.jpg` (items have `model_glb`, `model_bytes`, `image_local`). Resume: rerun `catalog.py`; URL discovery cached in `catalog_urls.json`.

## Amazon (not scraped)

Amazon was deliberately not scraped (bot wall, ToS forbid automated access). To add Amazon products legitimately:

- Register for Amazon Associates (needs an approved site/app and 3 qualifying sales in 180 days to keep PA-API access), then use the Product Advertising API 5.0 (SearchItems/GetItems) with access key, secret key, partner tag. It returns title, price, images, dimensions (ItemInfo.ProductInfo.ItemDimensions), features, and a detail-page URL, usually in inches/pounds.
- PA-API gives NO 3D models; Amazon 3D (Amazon View in 3D) GLBs are not exposed. Models would have to come from elsewhere or be generated (e.g. image-to-3D from the product photos), and dimensions are often missing or per-variant.
- Rate limits start at 1 request/s and scale with referred sales; images/prices may only be shown with the Associates link and must be refreshed within 24 h.
- Alternative: Rainforest/Keepa-type paid APIs (also ToS-grey), or a hand-curated list.
