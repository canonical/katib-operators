# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Katib Experiments.
"""

import logging

import lightkube
import pytest
from pytest_operator.plugin import OpsTest
from utils import (
    assert_deleted,
    assert_exp_status_running_succeeded,
    assert_get_experiment,
    create_experiment,
    delete_experiment,
)

logger = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "experiment_file",
    [
        "tests/assets/crs/bayesian-optimization.yaml",
        "tests/assets/crs/cmaes.yaml",
        "tests/assets/crs/darts-cpu.yaml",
        "tests/assets/crs/enas-cpu.yaml",
        "tests/assets/crs/file-metrics-collector.yaml",
        "tests/assets/crs/grid-example.yaml",
        "tests/assets/crs/hyperband.yaml",
        "tests/assets/crs/median-stop.yaml",
        "tests/assets/crs/random.yaml",
        "tests/assets/crs/simple-pbt.yaml",
    ],
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

    assert_get_experiment(lightkube_client, exp_name, namespace)
    assert_exp_status_running_succeeded(logger, lightkube_client, exp_name, namespace)

    delete_experiment(lightkube_client, exp_name, namespace)
    assert_deleted(logger, lightkube_client, exp_name, namespace)

    # Wait for applications to settle
    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=True,
        timeout=360,
    )
