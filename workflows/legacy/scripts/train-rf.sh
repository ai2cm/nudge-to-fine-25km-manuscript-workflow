#!/bin/bash

set -e

DATA=$1
TRAINING_CONFIG=$2
TIMES=$3
OUTPUT=$4

argo submit --from workflowtemplate/training \
    -p input="$DATA" \
    -p config="$(< $TRAINING_CONFIG)" \
    -p times="$(< $TIMES)" \
    -p output=$OUTPUT
