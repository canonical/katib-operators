"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

KATIB_DB_MANAGER = CharmSpec(charm="katib-db-manager", channel="latest/edge", trust=True)
