#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# static list
STATIC_IMAGE_LIST=(
)
# dynamic list
# switch to branch for 1.7/stable
git checkout origin/track/0.15
IMAGE_LIST=()
IMAGE_LIST+=($(grep image charms/katib-controller/src/suggestion.json | awk  '{print $2}'))
IMAGE_LIST+=($(grep image charms/katib-controller/src/suggestion.json | awk  '{print $2}'))
IMAGE_LIST+=($(grep image charms/katib-controller/src/enasCPUTemplate.yaml | awk  '{print $2}'))
IMAGE_LIST+=($(grep image charms/katib-controller/src/early-stopping.json | awk  '{print $2}'))
IMAGE_LIST+=($(grep image charms/katib-controller/src/defaultTrialTemplate.yaml | awk  '{print $2}'))
IMAGE_LIST+=($(grep image charms/katib-controller/src/pytorchJobTemplate.yaml | awk  '{print $2}'))
IMAGE_LIST+=($(grep image charms/katib-controller/src/metrics-collector-sidecar.json | awk  '{print $2}'))

printf "%s\n" "${STATIC_IMAGE_LIST[@]}"
printf "%s\n" "${IMAGE_LIST[@]}"
