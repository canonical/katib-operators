import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    assert_logging,
    deploy_and_assert_grafana_agent,
)
from charms_dependencies import MYSQL_K8S
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = "katib-db-manager"
DB_APP_NAME = "katib-db"


class TestCharm:
    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest, request):
        """Build and deploy the charm.
        Assert on the unit status.
        """
        entity_url = (
            await ops_test.build_charm(".")
            if not (entity_url := request.config.getoption("--charm-path"))
            else entity_url
        )
        image_path = METADATA["resources"]["oci-image"]["upstream-source"]
        resources = {"oci-image": image_path}

        await ops_test.model.deploy(
            entity_url, resources=resources, application_name=APP_NAME, trust=True
        )

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=60 * 10,
        )

        # deploy mysql-k8s charm
        await ops_test.model.deploy(
            entity_url=MYSQL_K8S.charm,
            application_name=DB_APP_NAME,
            channel=MYSQL_K8S.channel,
            config=MYSQL_K8S.config,
            trust=MYSQL_K8S.trust,
        )

        await ops_test.model.wait_for_idle(
            apps=[DB_APP_NAME],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=60 * 10,
        )

        # test no database relation, charm should be in blocked state
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

        # Deploying grafana-agent-k8s and add all relations
        await deploy_and_assert_grafana_agent(
            ops_test.model, APP_NAME, metrics=False, dashboard=False, logging=True
        )

    @pytest.mark.abort_on_fail
    async def test_relational_db_relation_with_mysql_k8s(self, ops_test: OpsTest):
        """Test no relation and relation with mysql-k8s charm."""

        # add relational-db relation which should put charm into active state
        await ops_test.model.integrate(f"{APP_NAME}:relational-db", f"{DB_APP_NAME}:database")

        # verify that charm goes into active state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

    async def test_logging(self, ops_test: OpsTest):
        """Test logging is defined in relation data bag."""
        app = ops_test.model.applications[GRAFANA_AGENT_APP]
        await assert_logging(app)
