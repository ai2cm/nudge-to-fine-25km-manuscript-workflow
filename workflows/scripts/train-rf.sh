#!/bin/bash

set -e

TRAINING_CONFIG=$1
DATA_CONFIG=$2
OUTPUT=$3

argo submit --from workflowtemplate/training \
    -p training_config="$(< $TRAINING_CONFIG)" \
    -p training_data_config="$(< $DATA_CONFIG)" \
    -p output=$OUTPUT \
    -p memory="20Gi" \
    -p flags="--cache.local_download_path train-data-download-dir"
