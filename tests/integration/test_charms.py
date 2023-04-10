# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import lightkube
import lightkube.generic_resource
import lightkube.resources.core_v1
import pytest
import tenacity
import yaml
from pytest_operator.plugin import OpsTest

CONTROLLER_PATH = Path("charms/katib-controller")
UI_PATH = Path("charms/katib-ui")
DB_PATH = Path("charms/katib-db-manager")

CONTROLLER_METADATA = yaml.safe_load(Path(f"{CONTROLLER_PATH}/metadata.yaml").read_text())
UI_METADATA = yaml.safe_load(Path(f"{UI_PATH}/metadata.yaml").read_text())
DB_METADATA = yaml.safe_load(Path(f"{DB_PATH}/metadata.yaml").read_text())

CONTROLLER_APP_NAME = CONTROLLER_METADATA["name"]
UI_APP_NAME = UI_METADATA["name"]
DB_APP_NAME = DB_METADATA["name"]

logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_deploy_katib_charms(ops_test: OpsTest):

    # Build katib-controller, katib-db-manager, and katib-ui charms
    controller_charm = await ops_test.build_charm(CONTROLLER_PATH)
    db_manager_charm = await ops_test.build_charm(DB_PATH)
    ui_charm = await ops_test.build_charm(UI_PATH)

    # Gather metadata
    controller_image_path = CONTROLLER_METADATA["resources"]["oci-image"]["upstream-source"]
    db_image_path = DB_METADATA["resources"]["oci-image"]["upstream-source"]
    ui_image_path = UI_METADATA["resources"]["oci-image"]["upstream-source"]

    # Deploy katib-controller, katib-db-manager, and katib-ui charms
    await ops_test.model.deploy(controller_charm, resources={"oci-image": controller_image_path})

    await ops_test.model.deploy(db_manager_charm, resources={"oci-image": db_image_path}, trust=True)

    await ops_test.model.deploy(ui_charm, resources={"oci-image": ui_image_path}, trust=True)

    # Deploy katib-db
    await ops_test.model.deploy(
        "charmed-osm-mariadb-k8s",
        application_name="katib-db",
        config={"database": "katib"},
    )

    # Relate to katib-db
    await ops_test.model.add_relation("katib-db-manager", "katib-db")

    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,
        timeout=90 * 10,
    )

    # Wait for everything to deploy
    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=True,
        timeout=360,
    )


async def test_create_experiment(ops_test: OpsTest):

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

    # Create Experiment resource
    exp_class = lightkube.generic_resource.create_namespaced_resource(
        group="kubeflow.org",
        version="v1beta1",
        kind="experiment",
        plural="experiments",
        verbs=None,
    )

    # Create Trial resource
    trial_class = lightkube.generic_resource.create_namespaced_resource(
        group="kubeflow.org",
        version="v1beta1",
        kind="trial",
        plural="trials",
        verbs=None,
    )

    # Create Experiment instance
    experiment_file = "examples/v1beta1/hp-tuning/grid-example.yaml"
    with open(experiment_file) as f:
        exp_object = exp_class(yaml.safe_load(f.read()))
        lightkube_client.create(exp_object, namespace=namespace)

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=15),
        stop=tenacity.stop_after_delay(30),
        reraise=True,
    )
    def assert_get_experiment():
        """Asserts on the presence of the experiment in the cluster.
        Retries multiple times using tenacity to allow time for the experiment
        to be created.
        """
        exp = lightkube_client.get(exp_class, name=exp_object.metadata.name, namespace=namespace)

        assert exp is not None, f"{exp_object.metadata.name} does not exist"

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=2, min=1, max=30),
        stop=tenacity.stop_after_attempt(10),
        reraise=True,
    )
    def assert_exp_status_running():
        """Asserts the experiment status is Running.
        Retries multiple times using tenacity to allow time for the experiment
        to change its status from None -> Created -> Running
        """
        exp_status = lightkube_client.get(
            exp_class.Status, name=exp_object.metadata.name, namespace=namespace
        ).status["conditions"][-1]["type"]

        logger.info(f"Experiment Status is {exp_status}")

        # Check experiment is running
        assert (
            exp_status == "Running"
        ), f"{exp_object.metadata.name} not running status = {exp_status})"

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=2, min=1, max=15),
        stop=tenacity.stop_after_attempt(10),
        reraise=True,
    )
    def assert_trial_status_running():
        """Asserts the trial status is Running.
        Retries multiple times using tenacity to allow the trial
        to be in Running state
        """
        trials = lightkube_client.list(trial_class, namespace=namespace)
        trial = next(trials)
        trial_status = trial.status["conditions"][-1]["type"]
        logger.info(f"Trial Status is {trial_status}")
        assert (
            trial_status == "Running"
        ), f"{trial.metadata.name} not running, status = {trial_status}"

    assert_get_experiment()
    assert_exp_status_running()
    assert_trial_status_running()
