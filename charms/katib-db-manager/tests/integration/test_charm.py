import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    assert_logging,
    deploy_and_assert_grafana_agent,
)
from ops.model import RelationNotFoundError
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = "katib-db-manager"
KATIB_DB_CONFIG = {"database": "katib"}


class TestCharm:
    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest):
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
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=60 * 10,
        )

        # deploy charmed-osm-mariadb-k8s charm
        await ops_test.model.deploy(
            entity_url="charmed-osm-mariadb-k8s",
            application_name="katib-db",
            config=KATIB_DB_CONFIG,
            trust=True
        )
        await ops_test.model.wait_for_idle(
            apps=["katib-db"],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=60 * 10,
        )

        # deploy mysql-k8s charm
        await ops_test.model.deploy("mysql-k8s", channel="8.0/stable", series="jammy", trust=True)
        await ops_test.model.wait_for_idle(
            apps=["mysql-k8s"],
            status="active",
            raise_on_blocked=True,
            timeout=60 * 10,
        )

        # test no database relation, charm should be in blocked state
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

        # Deploying grafana-agent-k8s and add all relations
        await deploy_and_assert_grafana_agent(
            ops_test.model, APP_NAME, metrics=False, dashboard=False, logging=True
        )

    @pytest.mark.abort_on_fail
    async def test_relational_mysql(self, ops_test: OpsTest):
        """Test adding mysql relation."""
        # add mysql relation and verify that charm reaches active state
        # NOTE: idle_period is used to ensure that relation data is propagated
        await ops_test.model.integrate(f"{APP_NAME}:mysql", "katib-db:mysql")
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
    async def test_relational_db_relation_with_mysql_relation(self, ops_test: OpsTest):
        """Test failure of addition of relational-db relation with mysql relation present."""

        # add relational-db relation which should put charm into blocked state,
        # because at this point mysql relation is already established
        await ops_test.model.integrate(f"{APP_NAME}:relational-db", "mysql-k8s:database")

        # verify that charm goes into blocked state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
            idle_period=10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

        # remove just added relational-db relation
        await ops_test.juju("remove-relation", f"{APP_NAME}:relational-db", "mysql-k8s:database")

    @pytest.mark.abort_on_fail
    async def test_relational_db_relation_with_mysql_k8s(self, ops_test: OpsTest):
        """Test no relation and relation with mysql-k8s charm."""

        # verify that charm is active state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

        # remove existing mysql relation which should put charm into blocked state,
        # because there will be no database relations
        await ops_test.juju("remove-relation", f"{APP_NAME}:mysql", "katib-db:mysql")

        # verify that charm goes into blocked state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

        # add relational-db relation which should put charm into active state
        await ops_test.model.integrate(f"{APP_NAME}:relational-db", "mysql-k8s:database")

        # verify that charm goes into active state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

    @pytest.mark.abort_on_fail
    async def test_msql_relation_with_relational_db_relation(self, ops_test: OpsTest):
        """Test failure of addition of mysql relation with relation-db relation present."""

        # add mysql relation which should put charm into blocked state,
        # because at this point relational-db relation is already established
        await ops_test.model.integrate(f"{APP_NAME}:mysql", "katib-db:mysql")

        # verify that charm goes into blocked state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

    async def test_logging(self, ops_test: OpsTest):
        """Test logging is defined in relation data bag."""
        app = ops_test.model.applications[GRAFANA_AGENT_APP]
        await assert_logging(app)
