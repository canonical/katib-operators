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

    # set default series for test model
    await ops_test.juju("model-config", "default-series=focal")

    await ops_test.model.deploy(
        charm_under_test, resources=resources, application_name=APP_NAME, trust=True
    )

    await ops_test.model.deploy(
        entity_url="charmed-osm-mariadb-k8s", application_name="katib-db", config=KATIB_DB_CONFIG
    )
    await ops_test.model.wait_for_idle(
        apps=["katib-db"],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=60 * 10,
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=60 * 10,
    )
    # test no database relation
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

    # add mysql relation and verify that charm reaches active state
    # NOTE: idle_period is used to ensure all resources are deployed and relations data is
    # propagated
    await ops_test.model.relate(f"{APP_NAME}:mysql", "katib-db:mysql")
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, "katib-db"],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=60 * 10,
        idle_period=60,
    )
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

@pytest.mark.abort_on_fail
async def test_relational_db_relation_with_mysql_relation(ops_test: OpsTest):
    """Test failure of addition of relational-db relation with mysql relation present."""
    await ops_test.model.deploy("mysql-k8s", channel="8.0/stable", series="jammy", trust=True)
    await ops_test.model.wait_for_idle(
        apps=["mysql-k8s"], status="active", raise_on_blocked=True, timeout=60 * 10, idle_period=30
    )
    
    # this relation creation should fail with log message
    await ops_test.model.relate(f"{APP_NAME}:relational-db", "mysql-k8s:mysql")

@pytest.mark.abort_on_fail
async def test_with_mysql_k8s(ops_test: OpsTest):
    """Test relation with mysql-k8s charm."""
    await ops_test.model.relate(f"{APP_NAME}:relational-db", "mysql-k8s:mysql")

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=600,
    )
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

@pytest.mark.abort_on_fail
async def test_msql_relation_with_relational_db_relation(ops_test: OpsTest):
    """Test failure of addition of mysql relation with relation-db relation present."""
    await ops_test.model.relate(f"{APP_NAME}:mysql", "katib-db:mysql")
    await ops_test.model.remove_relation(f"{APP_NAME}:relational-db", "katib-db:mysql")


