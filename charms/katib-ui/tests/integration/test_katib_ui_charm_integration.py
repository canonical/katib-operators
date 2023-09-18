from pathlib import Path

import json
from pathlib import Path
from typing import List
import pytest_asyncio
import requests
import pytest
import yaml
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]


@pytest_asyncio.fixture
async def ws_addresses(ops_test: OpsTest) -> List[str]:
    status = await ops_test.model.get_status()  # noqa: F821
    addresses = []
    for unit in list(status.applications[CHARM_NAME].units):
        addr = status["applications"][CHARM_NAME]["units"][unit]["address"]
        addresses.append(addr)
    return addresses

class TestCharm:
    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest):
        """Build and deploy the charm.

        Assert on the unit status.
        """
        charm_under_test = await ops_test.build_charm(".")
        image_path = METADATA["resources"]["oci-image"]["upstream-source"]
        resources = {"oci-image": image_path}

        await ops_test.model.deploy(
            charm_under_test, resources=resources, application_name=CHARM_NAME
        )

        await ops_test.model.wait_for_idle(
            apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=300
        )

    
    
    @pytest.mark.abort_on_fail
    async def test_ui_server_ready(self, ws_addresses: List[str]):
        """Verify that all katib-ui units report ready."""
        for addr in ws_addresses:
            url = f"http://{addr}:8080/katib"
            home = requests.get(url)
            assert home.status_code == 200
 