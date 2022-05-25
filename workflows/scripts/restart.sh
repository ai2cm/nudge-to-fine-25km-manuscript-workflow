#!/bin/bash

set -e

URL=$1
SEGMENTS=$2


argo submit --from workflowtemplate/restart-prognostic-run \
     -p url=$URL \
     -p segment-count=$SEGMENTS \
     -p cpu=24 \
     -p memory=25Gi
