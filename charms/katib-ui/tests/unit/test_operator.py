# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KatibUIOperator

TEST_NAMESPACE = "test-namespace"
TEST_PORT = 8080
ISTIO_INGRESS_ROUTE_RELATION = "istio-ingress-route"
INGRESS_RELATION = "ingress"
ISTIO_GATEWAY_APP = "istio-gateway"
ISTIO_INGRESS_K8S_APP = "istio-ingress-k8s"

EXPECTED_PEBBLE_LAYER = {
    "services": {
        "katib-ui": {
            "override": "replace",
            "summary": "entrypoint of the katib-ui-operator image",
            "command": f"./katib-ui --port={TEST_PORT}",
            "working-dir": "/app",
            "startup": "enabled",
            "environment": {"KATIB_CORE_NAMESPACE": TEST_NAMESPACE},
        }
    },
}


@pytest.fixture
def harness() -> Harness:
    """Returns a harnessed charm with leader == True."""
    harness = Harness(KatibUIOperator)
    harness.set_leader(True)
    harness.set_model_name(TEST_NAMESPACE)
    return harness


@pytest.fixture()
def mocked_resource_handler(mocker):
    """Yields a mocked resource handler."""
    mocked_resource_handler = MagicMock()
    mocked_resource_handler_factory = mocker.patch("charm.KRH")
    mocked_resource_handler_factory.return_value = mocked_resource_handler
    yield mocked_resource_handler


@pytest.fixture()
def mocked_lightkube_client(mocker, mocked_resource_handler):
    """Prevents lightkube clients from being created, returning a mock instead."""
    mocked_resource_handler.lightkube_client = MagicMock()
    yield mocked_resource_handler.lightkube_client


@pytest.fixture()
def mocked_kubernetes_service_patcher(mocker):
    """Mocks the KubernetesServicePatch for the charm."""
    mocked_service_patcher = mocker.patch("charm.KubernetesServicePatch")
    mocked_service_patcher.return_value = lambda x, y: None
    yield mocked_service_patcher


@pytest.fixture()
def mocked_istio_ingress_route_requirer(mocker):
    """Mocks the IstioIngressRouteRequirer for the charm."""
    mocked_istio_requirer = mocker.patch("charm.IstioIngressRouteRequirer")
    mocked_istio_requirer.return_value = MagicMock()
    yield mocked_istio_requirer


@pytest.fixture()
def mocked_service_mesh_consumer(mocker):
    """Mocks the ServiceMeshConsumer for the charm."""
    mocked_mesh_consumer = mocker.patch("charm.ServiceMeshConsumer")
    mocked_mesh_consumer.return_value = MagicMock()
    yield mocked_mesh_consumer


@pytest.fixture()
def mocked_kubeflow_dashboard_links_requirer(mocker):
    """Mocks the KubeflowDashboardLinksRequirer for the charm."""
    mocked_dashboard_links = mocker.patch("charm.KubeflowDashboardLinksRequirer")
    mocked_dashboard_links.return_value = MagicMock()
    yield mocked_dashboard_links


@pytest.fixture()
def mocked_load_in_cluster_generic_resources(mocker):
    """Mocks the load_in_cluster_generic_resources function."""
    mocked_load = mocker.patch("charm.load_in_cluster_generic_resources")
    yield mocked_load


def test_log_forwarding(
    harness,
    mocked_resource_handler,
    mocked_lightkube_client,
    mocked_kubernetes_service_patcher,
    mocked_istio_ingress_route_requirer,
    mocked_service_mesh_consumer,
    mocked_kubeflow_dashboard_links_requirer,
):
    """Test that LogForwarder is called on charm initialization."""
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_not_leader(
    harness,
    mocked_resource_handler,
    mocked_lightkube_client,
    mocked_kubernetes_service_patcher,
    mocked_istio_ingress_route_requirer,
    mocked_service_mesh_consumer,
    mocked_kubeflow_dashboard_links_requirer,
):
    """Test that charm waits if not leader."""
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_kubernetes_resources_created(
    harness,
    mocked_resource_handler,
    mocked_lightkube_client,
    mocked_kubernetes_service_patcher,
    mocked_istio_ingress_route_requirer,
    mocked_service_mesh_consumer,
    mocked_kubeflow_dashboard_links_requirer,
    mocked_load_in_cluster_generic_resources,
):
    """Test that Kubernetes resources are applied when conditions are met."""
    harness.begin_with_initial_hooks()

    # Act
    harness.charm.on.install.emit()

    # Assert
    mocked_resource_handler.apply.assert_called()
    assert isinstance(harness.charm.model.unit.status, ActiveStatus)


def test_pebble_layer(
    harness,
    mocked_resource_handler,
    mocked_lightkube_client,
    mocked_kubernetes_service_patcher,
    mocked_istio_ingress_route_requirer,
    mocked_service_mesh_consumer,
    mocked_kubeflow_dashboard_links_requirer,
    mocked_load_in_cluster_generic_resources,
):
    """Test creation of Pebble layer with correct configuration."""
    harness.begin_with_initial_hooks()

    # Act
    harness.charm.on.install.emit()

    # Assert
    pebble_plan = harness.get_container_pebble_plan("katib-ui")
    assert pebble_plan
    assert pebble_plan._services
    pebble_plan_info = pebble_plan.to_dict()

    # Check the service is configured correctly
    assert pebble_plan_info["services"]["katib-ui"]["command"] == f"./katib-ui --port={TEST_PORT}"
    assert pebble_plan_info["services"]["katib-ui"]["working-dir"] == "/app"
    assert pebble_plan_info["services"]["katib-ui"]["startup"] == "enabled"

    # Check environment variables
    test_env = pebble_plan_info["services"]["katib-ui"]["environment"]
    assert test_env["KATIB_CORE_NAMESPACE"] == TEST_NAMESPACE


def test_pebble_services_running(
    harness,
    mocked_resource_handler,
    mocked_lightkube_client,
    mocked_kubernetes_service_patcher,
    mocked_istio_ingress_route_requirer,
    mocked_service_mesh_consumer,
    mocked_kubeflow_dashboard_links_requirer,
    mocked_load_in_cluster_generic_resources,
):
    """Test that pebble services successfully start."""
    harness.begin_with_initial_hooks()

    # Act
    harness.charm.on.install.emit()

    # Assert
    container = harness.charm.unit.get_container("katib-ui")
    service = container.get_service("katib-ui")
    assert service.is_running()

    actual_layer = harness.get_container_pebble_plan("katib-ui").to_dict()
    assert EXPECTED_PEBBLE_LAYER == actual_layer


def test_ingress_relation_with_data(
    harness,
    mocked_resource_handler,
    mocked_lightkube_client,
    mocked_kubernetes_service_patcher,
    mocked_istio_ingress_route_requirer,
    mocked_service_mesh_consumer,
    mocked_kubeflow_dashboard_links_requirer,
    mocked_load_in_cluster_generic_resources,
):
    """Test that ingress relation data is sent when relation is present."""
    harness.begin_with_initial_hooks()

    # Setup ingress relation
    rel_id = harness.add_relation(INGRESS_RELATION, "istio-pilot")
    harness.add_relation_unit(rel_id, "istio-pilot/0")

    # Mock the interfaces
    mock_interface = MagicMock()
    with patch("charm.get_interfaces") as mock_get_interfaces:
        mock_get_interfaces.return_value = {INGRESS_RELATION: mock_interface}

        # Act
        harness.charm.on.install.emit()

        # Assert
        mock_interface.send_data.assert_called_once_with(
            {
                "prefix": "/katib/",
                "service": harness.charm.model.app.name,
                "port": harness.charm.model.config["port"],
            }
        )


def test_both_istio_relations_blocked(
    harness,
    mocked_resource_handler,
    mocked_lightkube_client,
    mocked_kubernetes_service_patcher,
    mocked_istio_ingress_route_requirer,
    mocked_service_mesh_consumer,
    mocked_kubeflow_dashboard_links_requirer,
    mocked_load_in_cluster_generic_resources,
):
    """Test that having both ambient and sidecar relations causes BlockedStatus."""
    harness.begin_with_initial_hooks()

    # Add both relations
    harness.add_relation(ISTIO_INGRESS_ROUTE_RELATION, ISTIO_INGRESS_K8S_APP)
    harness.add_relation(INGRESS_RELATION, ISTIO_GATEWAY_APP)

    # Act
    harness.charm.on.config_changed.emit()

    # Assert
    assert isinstance(harness.charm.model.unit.status, BlockedStatus)
    assert (
        f"Cannot have both '{ISTIO_INGRESS_ROUTE_RELATION}' and '{INGRESS_RELATION}' relations"
        in str(harness.charm.model.unit.status.message)
    )


def test_ambient_ingress_configuration_leader_only(
    harness,
    mocked_resource_handler,
    mocked_lightkube_client,
    mocked_kubernetes_service_patcher,
    mocked_istio_ingress_route_requirer,
    mocked_service_mesh_consumer,
    mocked_kubeflow_dashboard_links_requirer,
):
    """Test that ambient ingress configuration is only submitted by the leader."""
    harness.begin()

    # The ingress.submit_config should be called during __init__ when unit is leader
    mocked_istio_ingress_route_requirer.return_value.submit_config.assert_called()


def test_config_changed_event(
    harness,
    mocked_resource_handler,
    mocked_lightkube_client,
    mocked_kubernetes_service_patcher,
    mocked_istio_ingress_route_requirer,
    mocked_service_mesh_consumer,
    mocked_kubeflow_dashboard_links_requirer,
    mocked_load_in_cluster_generic_resources,
):
    """Test that config-changed event triggers the main handler."""
    harness.begin_with_initial_hooks()

    # Act
    harness.charm.on.config_changed.emit()

    # Assert
    mocked_resource_handler.apply.assert_called()
    assert isinstance(harness.charm.model.unit.status, ActiveStatus)
