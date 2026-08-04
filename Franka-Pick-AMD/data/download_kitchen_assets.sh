#!/usr/bin/env bash

set -e

ASSET_DIR="../assets/rustic_kitchen"

mkdir -p ${ASSET_DIR}

BASE_URL="https://wlt-ai-cdn.art/example_exports/rustic_kitchen_with_natural_light"

echo "Downloading Rustic Kitchen assets..."

wget -O ${ASSET_DIR}/rustic_kitchen_hq.glb \
    ${BASE_URL}/rustic_kitchen_with_natural_light_hq.glb

wget -O ${ASSET_DIR}/rustic_kitchen_collider.glb \
    ${BASE_URL}/rustic_kitchen_with_natural_light_collider.glb

echo "Download finished."