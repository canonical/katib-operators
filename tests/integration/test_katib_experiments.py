# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Katib Experiments."""

import glob
from pathlib import Path

import lightkube
import pytest
from lightkube import codecs
from lightkube.generic_resource import create_global_resource, load_in_cluster_generic_resources
from pytest_operator.plugin import OpsTest
from utils import (
    assert_experiment_deleted,
    assert_experiment_exists,
    assert_experiment_status_running_succeeded,
    create_experiment,
    delete_experiment,
)

PROFILE_TEMPLATE_FILE = Path("./tests/assets/crs/profile.yaml.j2")
NAMESPACE = "test-kubeflow"
PROFILE_RESOURCE = create_global_resource(
    group="kubeflow.org",
    version="v1",
    kind="Profile",
    plural="profiles",
)


@pytest.fixture(scope="module")
def lightkube_client() -> lightkube.Client:
    """Return a lightkube Client that can talk to the K8s API."""
    client = lightkube.Client(field_manager="katib-operators")
    load_in_cluster_generic_resources(client)
    return client


@pytest.fixture(scope="module")
def create_profile(lightkube_client):
    """Create Profile and handle cleanup at the end of the module tests."""
    resources = list(
        codecs.load_all_yaml(
            PROFILE_TEMPLATE_FILE.read_text(),
            context={"namespace": NAMESPACE},
        )
    )
    assert len(resources) == 1, f"Expected 1 Profile, got {len(resources)}!"
    lightkube_client.create(resources[0])

    yield

    # delete the Profile at the end of the module tests
    lightkube_client.delete(PROFILE_RESOURCE, name=NAMESPACE)


@pytest.mark.parametrize(
    "experiment_file",
    glob.glob("tests/assets/crs/experiments/*.yaml"),
)
async def test_katib_experiments(
    create_profile, lightkube_client, ops_test: OpsTest, experiment_file
):
    """Test Katib experiments.

    Create an experiment and assert that it is Running or Succeeded. Delete the experiment after it
    has completed.
    NOTE: This test is re-using the deployment created in test_charms::test_deploy_katib_charms().
    """
    exp_name = create_experiment(
        client=lightkube_client, exp_path=experiment_file, namespace=NAMESPACE
    )

    assert_experiment_exists(lightkube_client, exp_name, NAMESPACE)
    assert_experiment_status_running_succeeded(lightkube_client, exp_name, NAMESPACE)

    delete_experiment(lightkube_client, exp_name, NAMESPACE)
    assert_experiment_deleted(lightkube_client, exp_name, NAMESPACE)
