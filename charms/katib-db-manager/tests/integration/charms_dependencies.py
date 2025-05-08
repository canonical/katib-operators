"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

MYSQL_K8S = CharmSpec(
    charm="mysql-k8s", channel="8.0/stable", config={"profile": "testing"}, trust=True
)
