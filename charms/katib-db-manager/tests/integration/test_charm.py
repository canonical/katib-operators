import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = "katib-db-manager"
KATIB_DB_CONFIG = {"database": "katib"}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build and deploy the charm.
    Assert on the unit status.
    """
    charm_under_test = await ops_test.build_charm(".")
    logger.info(f"Built charm {charm_under_test}")
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        charm_under_test, resources=resources, application_name=APP_NAME, trust=True
    )

    await ops_test.model.deploy(
        entity_url="charmed-osm-mariadb-k8s", application_name="katib-db", config=KATIB_DB_CONFIG
    )
    await ops_test.model.add_relation(
        f"{APP_NAME}:mysql",
        "katib-db:mysql",
    )

    # NOTE: idle_period is used to ensure all resources are deployed
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=60 * 10, idle_period=30
    )
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

