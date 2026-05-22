"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

ISTIO_PILOT = CharmSpec(charm="istio-pilot", channel="1.28/edge", trust=True)
KUBEFLOW_PROFILES = CharmSpec(charm="kubeflow-profiles", channel="1.10/edge", trust=True)
MYSQL_K8S = CharmSpec(
    charm="mysql-k8s", channel="8.0/stable", trust=True, config={"profile": "testing"}
)
TRAINING_OPERATOR = CharmSpec(charm="training-operator", channel="2.1/edge", trust=True)
