# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Katib Experiments.
"""

import glob
import logging

import lightkube
import pytest
from pytest_operator.plugin import OpsTest
from utils import (
    assert_experiment_deleted,
    assert_experiment_exists,
    assert_experiment_status_running_succeeded,
    create_experiment,
    delete_experiment,
)

logger = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "experiment_file",
    glob.glob("tests/assets/crs/*.yaml"),
)
async def test_katib_experiments(ops_test: OpsTest, experiment_file):
    """Test Katib Experiments.

    Create experiment and assert that it is Running or Succeeded.
    At the end, experiment is deleted.
    NOTE: This test is re-using deployment created in test_deploy_katib_charms() in test_charms.py
    """
    namespace = ops_test.model_name
    lightkube_client = lightkube.Client()

    # Add metrics collector injection enabled label to namespace
    test_namespace = lightkube_client.get(
        res=lightkube.resources.core_v1.Namespace, name=namespace
    )
    test_namespace.metadata.labels.update(
        {"katib.kubeflow.org/metrics-collector-injection": "enabled"}
    )
    lightkube_client.patch(
        res=lightkube.resources.core_v1.Namespace,
        name=test_namespace.metadata.name,
        obj=test_namespace,
    )

    exp_name = create_experiment(
        client=lightkube_client, exp_path=experiment_file, namespace=namespace
    )

    assert_experiment_exists(lightkube_client, exp_name, namespace)
    assert_experiment_status_running_succeeded(logger, lightkube_client, exp_name, namespace)

    delete_experiment(lightkube_client, exp_name, namespace)
    assert_experiment_deleted(logger, lightkube_client, exp_name, namespace)

    # Wait for applications to settle
    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=True,
        timeout=360,
    )
