# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charms_dependencies import ISTIO_PILOT, KUBEFLOW_PROFILES, MYSQL_K8S
from pytest_operator.plugin import OpsTest

BUILD_SUFFIX = "_ubuntu@24.04-amd64.charm"

CONTROLLER_PATH = Path("charms/katib-controller")
UI_PATH = Path("charms/katib-ui")
DB_MANAGER_PATH = Path("charms/katib-db-manager")

CONTROLLER_METADATA = yaml.safe_load(Path(f"{CONTROLLER_PATH}/metadata.yaml").read_text())
UI_METADATA = yaml.safe_load(Path(f"{UI_PATH}/metadata.yaml").read_text())
DB_MANAGER_METADATA = yaml.safe_load(Path(f"{DB_MANAGER_PATH}/metadata.yaml").read_text())

CONTROLLER_APP_NAME = CONTROLLER_METADATA["name"]
UI_APP_NAME = UI_METADATA["name"]
DB_MANAGER_APP_NAME = DB_MANAGER_METADATA["name"]

DB_APP_NAME = "katib-db"


logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_deploy_katib_charms(ops_test: OpsTest, request):
    # Build katib-controller, katib-db-manager, and katib-ui charms
    if charms_path := request.config.getoption("--charms-path"):
        controller_charm = (
            f"{charms_path}/{CONTROLLER_APP_NAME}/{CONTROLLER_APP_NAME}{BUILD_SUFFIX}"
        )
        db_manager_charm = (
            f"{charms_path}/{DB_MANAGER_APP_NAME}/{DB_MANAGER_APP_NAME}{BUILD_SUFFIX}"
        )
        ui_charm = f"{charms_path}/{UI_APP_NAME}/{UI_APP_NAME}{BUILD_SUFFIX}"
    else:
        controller_charm = await ops_test.build_charm(CONTROLLER_PATH)
        db_manager_charm = await ops_test.build_charm(DB_MANAGER_PATH)
        ui_charm = await ops_test.build_charm(UI_PATH)

    # Gather metadata
    controller_image_path = CONTROLLER_METADATA["resources"]["oci-image"]["upstream-source"]
    db_manager_image_path = DB_MANAGER_METADATA["resources"]["oci-image"]["upstream-source"]
    ui_image_path = UI_METADATA["resources"]["oci-image"]["upstream-source"]

    # Deploy katib-controller, katib-db-manager, and katib-ui charms
    await ops_test.model.deploy(
        controller_charm, resources={"oci-image": controller_image_path}, trust=True
    )

    await ops_test.model.deploy(
        db_manager_charm, resources={"oci-image": db_manager_image_path}, trust=True
    )

    await ops_test.model.deploy(ui_charm, resources={"oci-image": ui_image_path}, trust=True)

    # Deploy katib-db
    await ops_test.model.deploy(
        entity_url=MYSQL_K8S.charm,
        application_name=DB_APP_NAME,
        channel=MYSQL_K8S.channel,
        config=MYSQL_K8S.config,
        trust=MYSQL_K8S.trust,
    )

    # Relate to katib-db
    await ops_test.model.add_relation(
        f"{DB_MANAGER_APP_NAME}:relational-db", f"{DB_APP_NAME}:database"
    )
    await ops_test.model.add_relation(DB_MANAGER_APP_NAME, CONTROLLER_APP_NAME)

    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,
        timeout=90 * 10,
    )

    # Deploy charms responsible for CRDs creation
    await ops_test.model.deploy(
        entity_url=KUBEFLOW_PROFILES.charm,
        channel=KUBEFLOW_PROFILES.channel,
        trust=KUBEFLOW_PROFILES.trust,
    )

    # The profile controller needs AuthorizationPolicies to create Profiles
    # Deploy istio-pilot to provide the k8s cluster with this CRD
    await ops_test.model.deploy(
        entity_url=ISTIO_PILOT.charm,
        channel=ISTIO_PILOT.channel,
        trust=ISTIO_PILOT.trust,
    )

    # Wait for everything to deploy
    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=True,
        timeout=360,
    )

    # wait for the webhook to be ready
