# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
import time
import pytest
import yaml
from pytest_operator.plugin import OpsTest
from lightkube.resources.core_v1 import Namespace
import lightkube
import logging
from lightkube.generic_resource import create_namespaced_resource

CONTROLLER_PATH = Path("charms/katib-controller")
UI_PATH = Path("charms/katib-ui")
DB_PATH = Path("charms/katib-db-manager")

CONTROLLER_METADATA = yaml.safe_load(
    Path(f"{CONTROLLER_PATH}/metadata.yaml").read_text()
)
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
    controller_image_path = CONTROLLER_METADATA["resources"]["oci-image"][
        "upstream-source"
    ]
    db_image_path = DB_METADATA["resources"]["oci-image"]["upstream-source"]
    ui_image_path = UI_METADATA["resources"]["oci-image"]["upstream-source"]

    # Deploy katib-controller, katib-db-manager, and katib-ui charms
    await ops_test.model.deploy(
        controller_charm, resources={"oci-image": controller_image_path}
    )

    await ops_test.model.deploy(
        db_manager_charm, resources={"oci-image": db_image_path}
    )

    await ops_test.model.deploy(
        ui_charm, resources={"oci-image": ui_image_path}, trust=True
    )

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
    this_ns = lightkube_client.get(res=Namespace, name=namespace)
    this_ns.metadata.labels.update(
        {"katib.kubeflow.org/metrics-collector-injection": "enabled"}
    )
    lightkube_client.patch(res=Namespace, name=this_ns.metadata.name, obj=this_ns)

    # Create Experiment resource
    Experiment = create_namespaced_resource(
        group="kubeflow.org",
        version="v1beta1",
        kind="experiment",
        plural="experiments",
        verbs=None,
    )

    # Create Experiment instance
    experiment_file = "examples/v1beta1/hp-tuning/grid-example.yaml"
    with open(experiment_file) as f:
        exp = Experiment(yaml.safe_load(f.read()))
        lightkube_client.create(exp, namespace=namespace)

    # Check if Experiment Succeeded
    for i in range(30):

        experiment = lightkube_client.get(Experiment, name="grid", namespace=namespace)

        try:
            status = experiment.get("status", {}).get("conditions")[-1].get("type")

        except TypeError:
            status = None

        if status == "Succeeded":
            logger.info("Experiment Succeeded")
            break

        else:
            logger.info(f"Waiting for Experiment.. Status: {status}")

        time.sleep(5)

    else:
        pytest.fail("Waited too long for Experiment!")
