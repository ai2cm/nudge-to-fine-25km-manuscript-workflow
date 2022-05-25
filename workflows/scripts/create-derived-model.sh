#!/bin/bash

set -e

CONFIG=$1
DESTINATION=$2

echo -n derived_model > name
gsutil -m cp name $DESTINATION/
gsutil -m cp $CONFIG $DESTINATION/derived_model.yaml
rm name
