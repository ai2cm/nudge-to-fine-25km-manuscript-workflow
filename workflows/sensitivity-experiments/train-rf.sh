#!/bin/bash

set -e

TRAINING_CONFIG=$1
DATA_CONFIG=$2
VALIDATION_DATA_CONFIG=$3
OUTPUT=$4

argo submit --from workflowtemplate/training \
    -p training_config="$(< $TRAINING_CONFIG)" \
    -p training_data_config="$(< $DATA_CONFIG)" \
    -p validation_data_config="$(< $VALIDATION_DATA_CONFIG)" \
    -p output=$OUTPUT \
    -p memory="27Gi" \
    -p flags="--cache.local_download_path train-data-download-dir"
