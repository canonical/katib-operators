#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# dynamic list
IMAGE_LIST=()
IMAGE_LIST+=($(find . -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \;))
IMAGE_LIST+=($(yq '.[]' ./charms/katib-controller/src/default-custom-images.json  | sed 's/"//g'))

# Exclude images for the trial templates
EXCLUDED_IMAGES=(
    "ghcr.io/kubeflow/katib/pytorch-mnist-cpu:v0.19.0"
    "ghcr.io/kubeflow/katib/enas-cnn-cifar10-cpu:v0.19.0"
)

# Filter the list
FILTERED_LIST=()
for img in "${IMAGE_LIST[@]}"; do
    skip=false
    for exclude in "${EXCLUDED_IMAGES[@]}"; do
        if [[ "$img" == "$exclude" ]]; then
            skip=true
            break
        fi
    done

    if [[ "$skip" == "false" ]]; then
        FILTERED_LIST+=("$img")
    fi
done

printf "%s\n" "${FILTERED_LIST[@]}"
