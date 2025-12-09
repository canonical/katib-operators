# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Jupyter UI Operator/Charm."""

from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    assert_path_reachable_through_ingress,
    assert_security_context,
    deploy_and_integrate_service_mesh_charms,
    generate_container_securitycontext_map,
    get_pod_names,
)
from lightkube import Client
from pytest_operator.plugin import OpsTest

EXPECTED_RESPONSE_TEXT = "Frontend"
HTTP_PATH = "/katib/"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)


@pytest.fixture(scope="session")
def lightkube_client() -> Client:
    """Returns lightkube Kubernetes client"""
    client = Client(field_manager=f"{APP_NAME}")
    return client


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, request):
    """Build and deploy the charm.

    Assert on the unit status.
    """
    # Keep the option to run the integration tests locally
    # by building the charm and then deploying
    entity_url = (
        await ops_test.build_charm("./")
        if not (entity_url := request.config.getoption("--charm-path"))
        else entity_url
    )
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url, resources=resources, application_name=APP_NAME, trust=True
    )

    # NOTE: idle_period is used to ensure all resources are deployed
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=60 * 10, idle_period=30
    )
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_deploy_and_relate_dependencies(ops_test: OpsTest):
    """Deploy and integrate Istio dependencies with the application under test."""
    await deploy_and_integrate_service_mesh_charms(
        app=APP_NAME,
        model=ops_test.model,
    )


@pytest.mark.abort_on_fail
async def test_ui_is_accessible(ops_test: OpsTest):
    """Verify that UI is accessible through the ingress gateway."""
    await assert_path_reachable_through_ingress(
        http_path=HTTP_PATH,
        namespace=ops_test.model_name,
        expected_content_type="text/html",
        expected_response_text=EXPECTED_RESPONSE_TEXT,
    )


@pytest.mark.parametrize("container_name", list(CONTAINERS_SECURITY_CONTEXT_MAP.keys()))
async def test_container_security_context(
    ops_test: OpsTest,
    lightkube_client: Client,
    container_name: str,
):
    """Test container security context is correctly set.

    Verify that container spec defines the security context with correct
    user ID and group ID.
    """
    pod_name = get_pod_names(ops_test.model.name, APP_NAME)[0]
    assert_security_context(
        lightkube_client,
        pod_name,
        container_name,
        CONTAINERS_SECURITY_CONTEXT_MAP,
        ops_test.model.name,
    )
