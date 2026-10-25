#!/bin/zsh
# fine-tune -> predict the 20 held-out plans with the new weights -> score against the reviewed labels
cd "$(dirname "$0")/../.." || exit 1
PY=feasibility/.venv/bin/python; W=feasibility/weights/cubicasa_ft1.pt
$PY app/plan3d/finetune.py --iters 3000 --out $W || exit 1
TEST=$($PY -c "import json;print(' '.join(json.load(open('app/plan3d/labels/split.json'))['test']))")
CUBI_WEIGHTS=$W CUBI_TAG=ft1 $PY app/plan3d/cubi.py predict --force ${=TEST} || exit 1
CUBI_TAG=ft1 $PY app/plan3d/labels.py score
echo "[ft] chain done"
