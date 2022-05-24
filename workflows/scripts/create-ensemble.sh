#!/bin/sh

set -e

TEMPLATE=$1
OUTPUT=$2

cat <<EOF > ensemble_model.yaml
models:
    - $TEMPLATE-seed-0
    - $TEMPLATE-seed-1
    - $TEMPLATE-seed-2
    - $TEMPLATE-seed-3
reduction: median
EOF

echo -n ensemble > name

gsutil -m cp ensemble_model.yaml $OUTPUT/
gsutil -m cp name $OUTPUT/

rm ensemble_model.yaml
rm name
