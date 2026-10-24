# Furniture catalogue report (final)

- Items: 359; with local GLB: 301 (416.3 MB total, avg 1.38 MB); with local image: 359; with image URL: 359; without GLB url: 58

## Per category

- armchair: 23
- bar_stool: 21
- bed: 12
- bookcase: 13
- coffee_table: 18
- desk: 19
- desk_chair: 8
- dining_chair: 31
- dining_table: 20
- dresser: 25
- floor_lamp: 6
- mirror: 8
- nightstand: 27
- plant_pot: 4
- rug: 32
- side_table: 20
- sofa: 16
- table_lamp: 3
- tv_bench: 36
- wardrobe: 17

## style_tags (all tags / primary tag)

- scandinavian: 304 / 252
- rustic: 146 / 58
- modern: 106 / 9
- minimal: 82 / 22
- classic: 30 / 5
- industrial: 17 / 6
- mid-century: 13 / 7

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
