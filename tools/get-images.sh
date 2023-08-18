#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# dynamic list
IMAGE_LIST=()
IMAGE_LIST+=($(find $REPO -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \;))
IMAGE_LIST+=($(grep image charms/katib-controller/src/suggestion.json | awk  '{print $2}' | sort --unique | sed s/\"//g | sed s/,//g))
IMAGE_LIST+=($(grep image charms/katib-controller/src/suggestion.json | awk  '{print $2}' | sort --unique | sed s/\"//g | sed s/,//g))
IMAGE_LIST+=($(grep image charms/katib-controller/src/enasCPUTemplate.yaml | awk  '{print $2}' | sort --unique | sed s/\"//g | sed s/,//g))
IMAGE_LIST+=($(grep image charms/katib-controller/src/early-stopping.json | awk  '{print $2}' | sort --unique | sed s/\"//g | sed s/,//g))
IMAGE_LIST+=($(grep image charms/katib-controller/src/defaultTrialTemplate.yaml | awk  '{print $2}' | sort --unique | sed s/\"//g | sed s/,//g))
IMAGE_LIST+=($(grep image charms/katib-controller/src/pytorchJobTemplate.yaml | awk  '{print $2}' | sort --unique | sed s/\"//g | sed s/,//g))
IMAGE_LIST+=($(grep image charms/katib-controller/src/metrics-collector-sidecar.json | awk  '{print $2}' | sort --unique | sed s/\"//g | sed s/,//g))
printf "%s\n" "${IMAGE_LIST[@]}"
