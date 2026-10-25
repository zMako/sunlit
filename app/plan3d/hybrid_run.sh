#!/bin/zsh
# switch the live layouts to the hybrid model: fine-tuned walls + crop, pretrained windows + doors (cubi.WALLS_TAG / ICONS_TAG)
cd "$(dirname "$0")/../.." || exit 1
PY=feasibility/.venv/bin/python; P=app/plan3d; set -e
echo "[hybrid] 1/7 predict every plan with the fine-tuned weights"
CUBI_WEIGHTS=feasibility/weights/cubicasa_ft1.pt CUBI_TAG=ft1 $PY $P/cubi.py predict
echo "[hybrid] 2/7 back up the live (pretrained-model) layouts to layouts_zs/"
rm -rf $P/layouts_zs && cp -R $P/layouts $P/layouts_zs
echo "[hybrid] 3/7 rebuild offline into layouts_cubi/"
rm -rf $P/layouts_cubi && $PY $P/rebuild.py
echo "[hybrid] 4/7 promote (no protected units) and archive saved furnishing plans of rebuilt units (room ids change)"
$PY $P/rebuild.py --promote
A=app/furnish/plans_archive/$(date +%Y%m%d_%H%M); mkdir -p $A
for f in app/furnish/plans/gs-*__*.json(N) app/furnish/plans/udr-*__*.json(N); do mv "$f" $A/; done
echo "[hybrid] 5/7 room names from plan text"
$PY $P/room_names.py
echo "[hybrid] 6/7 townhouse levels, stairs, slabs"
$PY $P/levels.py
echo "[hybrid] 7/7 doors: standard widths, swing from the drawn arc, style from the listing photos"
[ -f $P/door_styles.json ] || $PY $P/door_styles.py
$PY $P/doors.py
echo "[hybrid] done"
