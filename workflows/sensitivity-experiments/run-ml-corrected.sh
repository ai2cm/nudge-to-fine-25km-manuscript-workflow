#!/bin/bash

set -e

TAG=n2f-25km-$1
RESTARTS=$2
BASE_CONFIG=$3
NUDGING_TENDENCY_MODEL_TEMPLATE=$4
SEEDS=$5
SEGMENTS=$6
RADIATIVE_FLUX_MODEL=$7

for SEED in $SEEDS
do
    RANDOM=$(openssl rand --hex 6)
    CONFIG=./workflows/ml-corrected-runs/tmp-seed-$SEED.yaml
    cp $BASE_CONFIG $CONFIG
    NUDGING_TENDENCY_MODEL=$NUDGING_TENDENCY_MODEL_TEMPLATE-seed-$SEED
    sed -i "s#RADIATIVE_FLUX_MODEL#$RADIATIVE_FLUX_MODEL#g" $CONFIG
    sed -i "s#NUDGING_TENDENCY_MODEL#$NUDGING_TENDENCY_MODEL#g" $CONFIG

    n=0
    until [ "$n" -ge 5 ]
    do
        argo submit --from workflowtemplate/prognostic-run \
            -p bucket=vcm-ml-experiments \
            -p project=spencerc \
            -p tag=${TAG}-seed-$SEED \
            -p config="$(< $CONFIG)" \
            -p reference-restarts=$RESTARTS \
            -p initial-condition="20180801.000000" \
            -p segment-count="$SEGMENTS" \
            -p memory="20Gi" \
            -p cpu="24" \
            --name "${TAG}-s${SEED}-$RANDOM" && break
        echo "Job submission failed; trying again in five seconds."
        n=$((n+1))
        sleep 5
    done

    rm $CONFIG
done
