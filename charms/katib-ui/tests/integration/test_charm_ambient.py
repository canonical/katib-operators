# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Katib UI Operator/Charm."""

from pathlib import Path

import pytest
import pytest_asyncio
import tenacity
import yaml
from charmed_kubeflow_chisme.testing import (
    ISTIO_INGRESS_K8S_APP,
    ISTIO_INGRESS_ROUTE_ENDPOINT,
    assert_path_reachable_through_ingress,
    deploy_and_integrate_service_mesh_charms,
)
from charms_dependencies import KATIB_DB_MANAGER
from lightkube import Client
from lightkube.generic_resource import create_namespaced_resource
from pytest_operator.plugin import OpsTest

EXPECTED_RESPONSE_TEXT = "Frontend"
HTTP_PATH = "/katib/"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

# A second istio-ingress-k8s instance used to verify multiple-ingress support.
SECOND_INGRESS_APP = "istio-ingress-k8s-alt"
INGRESS_CHANNEL = "2/stable"
# Name of the HTTPRoute submitted by katib-ui (see charm._ambient_mesh_ingress).
INGRESS_ROUTE_NAME = "http-route"
# Gateway listener section for cleartext HTTP on port 80.
HTTP_SECTION_NAME = "http-80"
# Path matched by the katib-ui HTTPRoute.
INGRESS_ROUTE_PATH = HTTP_PATH
# Gateway API generic resources, resolved at runtime via lightkube.
HTTPROUTE_RESOURCE = create_namespaced_resource(
    "gateway.networking.k8s.io", "v1", "HTTPRoute", "httproutes"
)
GATEWAY_RESOURCE = create_namespaced_resource(
    "gateway.networking.k8s.io", "v1", "Gateway", "gateways"
)
RETRY_120_SECONDS = tenacity.Retrying(
    stop=tenacity.stop_after_delay(120),
    wait=tenacity.wait_fixed(2),
    reraise=True,
)


@pytest_asyncio.fixture
async def lightkube_client():
    client = Client(field_manager="test")
    yield client


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

    # The k8s-service-info relation is optional: katib-ui should reach active status on its
    # own, falling back to the Kubernetes-injected katib-db-manager Service env vars.
    # NOTE: idle_period is used to ensure all resources are deployed
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=60 * 10, idle_period=30
    )
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

    # Deploy dependency katib-db-manager and integrate to provide the
    # k8s-service-info relation, then assert katib-ui is still active.
    await ops_test.model.deploy(
        KATIB_DB_MANAGER.charm, channel=KATIB_DB_MANAGER.channel, trust=KATIB_DB_MANAGER.trust
    )
    await ops_test.model.integrate(APP_NAME, KATIB_DB_MANAGER.charm)

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


async def assert_ui_is_accessible(ops_test: OpsTest):
    """Verify that UI is accessible through the ingress gateway."""
    await assert_path_reachable_through_ingress(
        http_path=HTTP_PATH,
        namespace=ops_test.model_name,
        expected_content_type="text/html",
        expected_response_text=EXPECTED_RESPONSE_TEXT,
    )


@pytest.mark.abort_on_fail
async def test_ui_is_accessible(ops_test: OpsTest):
    """Verify that UI is accessible through the ingress gateway before the second ingress."""
    await assert_ui_is_accessible(ops_test)


@pytest.mark.abort_on_fail
async def test_deploy_and_relate_second_ingress(ops_test: OpsTest):
    """Deploy a second istio-ingress-k8s and relate it to katib-ui.

    katib-ui must accept more than one istio-ingress-route relation without
    erroring, so it should remain active after the second ingress is related.
    """
    await ops_test.model.deploy(
        ISTIO_INGRESS_K8S_APP,
        application_name=SECOND_INGRESS_APP,
        channel=INGRESS_CHANNEL,
        trust=True,
    )
    await ops_test.model.wait_for_idle(
        [SECOND_INGRESS_APP],
        raise_on_blocked=False,
        raise_on_error=False,
        wait_for_active=True,
        timeout=60 * 15,
    )

    await ops_test.model.integrate(
        f"{SECOND_INGRESS_APP}:{ISTIO_INGRESS_ROUTE_ENDPOINT}",
        f"{APP_NAME}:{ISTIO_INGRESS_ROUTE_ENDPOINT}",
    )
    await ops_test.model.wait_for_idle(
        [APP_NAME, SECOND_INGRESS_APP],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=60 * 10,
        idle_period=30,
    )

    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


async def test_httproute_attached_to_second_gateway(ops_test: OpsTest, lightkube_client: Client):
    """Verify the HTTPRoute for the second ingress is created and bound to its Gateway.

    The istio-ingress-k8s charm names each route
    ``{source_app}-{route_name}-httproute-{section}-{ingress_app}`` and binds it to a
    Gateway named after the ingress application via ``parentRefs``. We assert that the
    route created for the second ingress is attached to the *second* Gateway (not the
    first) and routes the katib-ui path to the katib-ui backend.
    """
    namespace = ops_test.model_name

    expected_route_name = (
        f"{APP_NAME}-{INGRESS_ROUTE_NAME}-httproute-{HTTP_SECTION_NAME}-{SECOND_INGRESS_APP}"
    )

    # The second Gateway should exist, named after the second ingress application.
    lightkube_client.get(GATEWAY_RESOURCE, name=SECOND_INGRESS_APP, namespace=namespace)

    # Retry to give the ingress charm time to reconcile the HTTPRoute resources.
    httproute = None
    for attempt in RETRY_120_SECONDS:
        with attempt:
            httproute = lightkube_client.get(
                HTTPROUTE_RESOURCE, name=expected_route_name, namespace=namespace
            )

    parent_refs = httproute.spec["parentRefs"]
    assert len(parent_refs) == 1
    # The route must be attached to the SECOND gateway, not the first.
    assert parent_refs[0]["name"] == SECOND_INGRESS_APP
    assert parent_refs[0]["sectionName"] == HTTP_SECTION_NAME

    # And it must route the katib-ui path to the katib-ui backend.
    rule = httproute.spec["rules"][0]
    assert rule["matches"][0]["path"]["value"] == INGRESS_ROUTE_PATH
    assert rule["backendRefs"][0]["name"] == APP_NAME


@pytest.mark.abort_on_fail
async def test_ui_is_accessible_after_second_ingress(ops_test: OpsTest):
    """Verify that UI is still accessible through the ingress gateway after the second ingress."""
    await assert_ui_is_accessible(ops_test)
