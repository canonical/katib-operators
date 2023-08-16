# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Katib Experiments.
"""

import glob
from pathlib import Path

import lightkube
import pytest
import yaml
from lightkube import codecs
from lightkube.generic_resource import create_global_resource
from pytest_operator.plugin import OpsTest
from utils import (
    assert_experiment_deleted,
    assert_experiment_exists,
    assert_experiment_status_running_succeeded,
    create_experiment,
    delete_experiment,
)



def _safe_load_file_to_text(filename: str):
    """Returns the contents of filename if it is an existing file, else it returns filename."""
    try:
        text = Path(filename).read_text()
    except FileNotFoundError:
        text = filename
    return text

@pytest.fixture(scope="module")
def lightkube_client() -> lightkube.Client:
    """Returns a lightkube Client that can talk to the K8s API."""
    client = lightkube.Client(field_manager="katib-operators")
    return client

@pytest.fixture(scope="module")
def profile(lightkube_client):
    """Creates a Profile object in cluster, cleaning it up after tests."""
    profile_file = "./tests/assets/crs/profile.yaml"
    yaml_text = _safe_load_file_to_text(profile_file)
    yaml_rendered = yaml.safe_load(yaml_text)
    profile_name = yaml_rendered["metadata"]["name"]

    create_global_resource(group="kubeflow.org", version="v1", kind="Profile", plural="profiles")

    for obj in codecs.load_all_yaml(yaml_text):
        try:
            lightkube_client.apply(obj)
        except lightkube.core.exceptions.ApiError as e:
            raise e

    yield profile_name

    delete_all_from_yaml(yaml_text, lightkube_client)


def delete_all_from_yaml(yaml_file: str, lightkube_client):
    """Deletes all k8s resources listed in a YAML file via lightkube.

    Args:
        yaml_file (str or Path): Either a string filename or a string of valid YAML.  Will attempt
                                 to open a filename at this path, failing back to interpreting the
                                 string directly as YAML.
        lightkube_client: Instantiated lightkube client or None
    """
    yaml_text = _safe_load_file_to_text(yaml_file)

    for obj in codecs.load_all_yaml(yaml_text):
        lightkube_client.delete(type(obj), obj.metadata.name)


@pytest.mark.parametrize(
    "experiment_file",
    glob.glob("tests/assets/crs/experiments/*.yaml"),
)
async def test_katib_experiments(profile: str, lightkube_client, ops_test: OpsTest, experiment_file):
    """Test Katib Experiments.

    Create experiment and assert that it is Running or Succeeded.
    At the end, experiment is deleted.
    NOTE: This test is re-using deployment created in test_deploy_katib_charms() in test_charms.py
    """
    profile_name = profile

    exp_name = create_experiment(
        client=lightkube_client, exp_path=experiment_file, namespace=profile_name
    )

    assert_experiment_exists(lightkube_client, exp_name, profile_name)
    assert_experiment_status_running_succeeded(lightkube_client, exp_name, profile_name)

    delete_experiment(lightkube_client, exp_name, profile_name)
    assert_experiment_deleted(lightkube_client, exp_name, profile_name)

    # Wait for applications to settle
    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=True,
        timeout=360,
    )
