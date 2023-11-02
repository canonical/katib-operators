## Katib Operators

### Overview
This bundle encompasses the Kubernetes python operators (a.k.a. charms) for Katib
(see [CharmHub](https://charmhub.io/?q=katib)). 

The Katib operators are python scripts that wrap the latest released [Katib manifests][manifests],
providing lifecycle management for each application, handling events (install, upgrade,
integrate, remove).

[manifests]: https://github.com/kubeflow/katib/tree/master/manifests

## Install the Katib operators on your K8s cluster

### 1. Install the Juju OLM 

    snap install juju --classic

Alternatively, you can `brew install juju` on macOS or download the [Juju installer for Windows](https://launchpad.net/juju/2.8/2.8.5/+download/juju-setup-2.8.5-signed.exe).

### 2. Point Juju to your Kubernetes cluster
   
    juju add-k8s myk8scloud --cluster=foo --kubeconfig=path/to/config 
   
   If you are on ASK, EKS, or GKE, append `--aks`, `--eks`, or `--gke`. 

   For more, see [Juju docs](https://juju.is/docs/clouds).
   
### 3. Create a Juju controller and bootstrap to your cluster

    juju bootstrap myk8scloud my-controller
   
   further reading on this step can be found in the [juju docs](https://juju.is/docs/creating-a-controller).
   
### 4. Create a Juju model

A Juju model is a blank canvas where your charm operators will be deployed. While creating a model, you can specify a name, e.g. `kf`, and your applications will be deployed into a Kubernetes namespace with the name you define at this point.

Create a Juju model with the command:

    juju add-model kf

### 5. Deploy the Katib bundle

To install Katib, run:

    juju deploy katib

You can also install each application individually, like this:

    juju deploy <application>

where `<application>` is one of `katib-controller`, `katib-ui`, or `katib-db-manager`.

**Note**: As a default, when you `juju deploy` an application or the full Katib
bundle, you will deploy the latest pushed commit of Katib, even if unreleased updates are
already available in the Kubeflow manifests. If you would like to try the latest
available charm run:


    juju deploy foo --channel=edge

### 6. (optional) Relate the Katib bundle with your Kubeflow

If you aim to use Katib within an existing Kubeflow deployment in order to use it within the Kubeflow dashboard, you will have to integrate `katib-ui` to `istio-pilot` with the following command:

    juju relate istio-pilot katib-ui

## Setting Custom Images for Katib Controller

Katib controller comes with a set of preconfigured images that are used in Katib workloads. This is the list of default images used in charm.

```json
{
    "default_trial_template": "docker.io/kubeflowkatib/mxnet-mnist:v0.16.0",
    "early_stopping__medianstop": "docker.io/kubeflowkatib/earlystopping-medianstop:v0.16.0",
    "metrics_collector_sidecar__stdout": "docker.io/kubeflowkatib/file-metrics-collector:v0.16.0",
    "metrics_collector_sidecar__file": "docker.io/kubeflowkatib/file-metrics-collector:v0.16.0",
    "metrics_collector_sidecar__tensorflow_event": "docker.io/kubeflowkatib/tfevent-metrics-collector:v0.16.0",
    "suggestion__random": "docker.io/kubeflowkatib/suggestion-hyperopt:v0.16.0",
    "suggestion__tpe": "docker.io/kubeflowkatib/suggestion-hyperopt:v0.16.0",
    "suggestion__grid": "docker.io/kubeflowkatib/suggestion-optuna:v0.16.0",
    "suggestion__hyperband": "docker.io/kubeflowkatib/suggestion-hyperband:v0.16.0",
    "suggestion__bayesianoptimization": "docker.io/kubeflowkatib/suggestion-skopt:v0.16.0",
    "suggestion__cmaes": "docker.io/kubeflowkatib/suggestion-goptuna:v0.16.0",
    "suggestion__sobol": "docker.io/kubeflowkatib/suggestion-goptuna:v0.16.0",
    "suggestion__multivariate_tpe": "docker.io/kubeflowkatib/suggestion-optuna:v0.16.0",
    "suggestion__enas": "docker.io/kubeflowkatib/suggestion-enas:v0.16.0",
    "suggestion__darts": "docker.io/kubeflowkatib/suggestion-darts:v0.16.0",
    "suggestion__pbt": "docker.io/kubeflowkatib/suggestion-pbt:v0.16.0",
}
```

These images can be overridden in the charm configuration under custom_images in the charms/katib-controller/config.yaml file. Whenever you leave the image field empty in the config, the default image will be used. You can specify your own images with the config by filling one or multiple entries. The config accepts either YAML or JSON entries. For example.

```
juju config katib-controller custom_images='{"default_trial_template": "custom:1.0", "early_stopping__medianstop": "cuustom:2.1"}'
```

These images are being used in *.j2 files under charms/katib-controller/src/templates/*.j2. 
