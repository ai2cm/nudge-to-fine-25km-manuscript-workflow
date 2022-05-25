#!/bin/bash

set -e

DATA=$1
BASE_TRAINING_CONFIG=$2
TIMES=$3
OUTPUT=$4

for SEED in {3..3}
do
    TRAINING_CONFIG=./tmp-seed-$SEED.yml
    cp $BASE_TRAINING_CONFIG $TRAINING_CONFIG
    sed -i "s/^    random_seed: .*$/    random_seed: $SEED/" $TRAINING_CONFIG
    argo submit --from workflowtemplate/training \
        -p input="$DATA" \
        -p config="$(< $TRAINING_CONFIG)" \
        -p times="$(< $TIMES)" \
        -p output=$OUTPUT-seed-$SEED \
        -p memory="20Gi" \
        -p flags="--local-download-path train-data-download-dir"
    rm $TRAINING_CONFIG
done
