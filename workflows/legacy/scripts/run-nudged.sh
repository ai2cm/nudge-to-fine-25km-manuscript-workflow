#!/bin/bash

set -e

TAG=n2f-25km-$1
RESTARTS=$2
CONFIG=$3
RANDOM=$(openssl rand --hex 6)

argo submit --from workflowtemplate/prognostic-run \
    -p bucket=vcm-ml-experiments \
    -p project=spencerc \
    -p tag=${TAG} \
    -p config="$(< $CONFIG)" \
    -p reference-restarts=$RESTARTS \
    -p initial-condition="20170801.010000" \
    -p segment-count="74" \
    -p memory="20Gi" \
    -p cpu="24" \
    --name "${TAG}-nudge-to-fine-${RANDOM}"
