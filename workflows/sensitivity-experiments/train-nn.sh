#!/bin/bash

set -e

BASE_TRAINING_CONFIG=$1
DATA_CONFIG=$2
VALIDATION_DATA_CONFIG=$3
SEED=$4
OUTPUT=$5

TRAINING_CONFIG=./workflows/ml-training/tmp-seed-$SEED.yml
cp $BASE_TRAINING_CONFIG $TRAINING_CONFIG
sed -i "s/^random_seed: .*$/random_seed: $SEED/" $TRAINING_CONFIG
argo submit --from workflowtemplate/training \
    -p training_config="$(< $TRAINING_CONFIG)" \
    -p training_data_config="$(< $DATA_CONFIG)" \
    -p validation_data_config="$(< $VALIDATION_DATA_CONFIG)" \
    -p output=$OUTPUT-seed-$SEED \
    -p memory="27Gi" \
    -p flags="--cache.local_download_path train-data-download-dir"
rm $TRAINING_CONFIG
