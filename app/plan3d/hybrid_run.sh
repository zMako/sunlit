#!/bin/zsh
# switch the live layouts to the hybrid model: fine-tuned walls + crop, pretrained windows + doors (cubi.WALLS_TAG / ICONS_TAG)
cd "$(dirname "$0")/../.." || exit 1
PY=feasibility/.venv/bin/python; P=app/plan3d; set -e
echo "[hybrid] 1/6 predict every plan with the fine-tuned weights"
CUBI_WEIGHTS=feasibility/weights/cubicasa_ft1.pt CUBI_TAG=ft1 $PY $P/cubi.py predict
echo "[hybrid] 2/6 back up the live (pretrained-model) layouts to layouts_zs/"
rm -rf $P/layouts_zs && cp -R $P/layouts $P/layouts_zs
echo "[hybrid] 3/6 rebuild offline into layouts_cubi/"
rm -rf $P/layouts_cubi && $PY $P/rebuild.py
echo "[hybrid] 4/6 promote (no protected units) and archive saved furnishing plans of rebuilt units (room ids change)"
$PY $P/rebuild.py --promote
A=app/furnish/plans_archive/$(date +%Y%m%d_%H%M); mkdir -p $A
for f in app/furnish/plans/gs-*__*.json(N) app/furnish/plans/udr-*__*.json(N); do mv "$f" $A/; done
echo "[hybrid] 5/6 room names from plan text"
$PY $P/room_names.py
echo "[hybrid] 6/6 townhouse levels, stairs, slabs"
$PY $P/levels.py
echo "[hybrid] done"
