# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

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

KUBEFLOW_PROFILES = "kubeflow-profiles"
KUBEFLOW_PROFILES_CHANNEL = "latest/edge"
KUBEFLOW_PROFILES_TRUST = True

MYSQL = "mysql-k8s"
MYSQL_CHANNEL = "8.0/stable"
MYSQL_CONFIG = {"profile": "testing"}
MYSQL_TRUST = True
MYSQL_CONSTRAINTS = {"mem": 2048}

logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_deploy_katib_charms(ops_test: OpsTest):
    # Build katib-controller, katib-db-manager, and katib-ui charms
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
        entity_url=MYSQL,
        application_name=DB_APP_NAME,
        channel=MYSQL_CHANNEL,
        config=MYSQL_CONFIG,
        constraints=MYSQL_CONSTRAINTS,
        trust=MYSQL_TRUST,
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
        entity_url=KUBEFLOW_PROFILES,
        channel=KUBEFLOW_PROFILES_CHANNEL,
        trust=KUBEFLOW_PROFILES_TRUST,
    )

    # Wait for everything to deploy
    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=True,
        timeout=360,
    )
