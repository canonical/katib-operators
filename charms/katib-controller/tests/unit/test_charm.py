# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ops.model import ActiveStatus, BlockedStatus, TooManyRelatedAppsError
from ops.testing import Harness

from charm import KatibControllerOperator

IMAGES_CONTEXT = json.loads(Path("src/default-custom-images.json").read_text())

TEST_NAMESPACE = "test-namespace"
K8S_SERVICE_INFO_RELATION_NAME = "k8s-service-info"
K8S_SERVICE_INFO_RELATION_DATA = {"name": "service-name", "port": "1234"}
EXPECTED_PEBBLE_LAYER = {
    "services": {
        "katib-controller": {
            "override": "replace",
            "summary": "Entry point for katib-controller image",
            "command": "./katib-controller --katib-config=/katib-config/katib-config.yaml",  # noqa E501
            "startup": "enabled",
            "environment": {
                "KATIB_CORE_NAMESPACE": f"{TEST_NAMESPACE}",
                "KATIB_DB_MANAGER_SERVICE_PORT": f"{K8S_SERVICE_INFO_RELATION_DATA['port']}",
            },
        }
    }
}


@pytest.fixture
def harness() -> Harness:
    harness = Harness(KatibControllerOperator)
    return harness


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client


@pytest.fixture()
def mocked_kubernetes_service_patch(mocker):
    """Mocks the KubernetesServicePatch for the charm."""
    mocked_kubernetes_service_patch = mocker.patch(
        "charm.KubernetesServicePatch", lambda x, y, service_name: None
    )
    yield mocked_kubernetes_service_patch


def test_log_forwarding(harness, mocked_lightkube_client, mocked_kubernetes_service_patch):
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_not_leader(harness, mocked_lightkube_client, mocked_kubernetes_service_patch):
    """Test when we are not the leader."""
    harness.begin_with_initial_hooks()
    # Assert that we are not Active, and that the leadership-gate is the cause.
    assert not isinstance(harness.charm.model.unit.status, ActiveStatus)
    assert harness.charm.model.unit.status.message.startswith("[leadership-gate]")


def test_kubernetes_resources_created_method(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Test whether we try to create Kubernetes resources when we have leadership."""
    # Arrange
    # Needed because kubernetes component will only apply to k8s if we are the leader
    harness.set_leader(True)
    harness.begin()

    # Need to mock the leadership-gate to be active, and the kubernetes auth component so that it
    # sees the expected resources when calling _get_missing_kubernetes_resources

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.kubernetes_resources.component._get_missing_kubernetes_resources = MagicMock(
        return_value=[]
    )

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert mocked_lightkube_client.apply.call_count == 13
    assert isinstance(harness.charm.kubernetes_resources.status, ActiveStatus)


def test_get_certs(harness, mocked_lightkube_client, mocked_kubernetes_service_patch):
    """Test certs generated on init."""
    # Act
    harness.begin()

    # Assert
    cert_attributes = ["cert", "ca", "key"]

    # Certs should be available
    for attr in cert_attributes:
        assert hasattr(harness.charm._stored, attr)


def test_no_k8s_service_info_relation(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Test the k8s_service_info component and charm are not active when no relation is present."""
    harness.set_leader(True)
    harness.begin_with_initial_hooks()

    assert (
        "Missing relation with a k8s service info provider. Please add the missing relation."
        in harness.charm.k8s_service_info_requirer.status.message
    )
    assert isinstance(harness.charm.k8s_service_info_requirer.status, BlockedStatus)
    assert not isinstance(harness.charm.model.unit.status, ActiveStatus)


def test_many_k8s_service_info_relations(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Test the k8s_service_info component and charm are not active when >1
    k8s_service_info relations are present.
    """
    harness.set_leader(True)

    setup_k8s_service_info_relation(harness, "remote-app-one")
    setup_k8s_service_info_relation(harness, "remote-app-two")

    harness.begin_with_initial_hooks()

    with pytest.raises(TooManyRelatedAppsError) as error:
        harness.charm.k8s_service_info_requirer.get_status()

    assert "Too many remote applications on k8s-service-info (2 > 1)" in error.value.args
    assert not isinstance(harness.charm.model.unit.status, ActiveStatus)


def test_pebble_services_running(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Test that if the Kubernetes Component is Active, the pebble services successfully start."""
    # Arrange
    harness.set_model_name(TEST_NAMESPACE)
    setup_k8s_service_info_relation(harness, "remote-test-app")
    harness.begin_with_initial_hooks()
    harness.set_can_connect("katib-controller", True)

    # Mock:
    # * leadership_gate to have get_status=>Active
    # * kubernetes_resources to have get_status=>Active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    container = harness.charm.unit.get_container("katib-controller")
    service = container.get_service("katib-controller")
    assert service.is_running()
    actual_layer = harness.get_container_pebble_plan("katib-controller").to_dict()
    assert EXPECTED_PEBBLE_LAYER == actual_layer


def setup_k8s_service_info_relation(harness: Harness, name: str):
    rel_id = harness.add_relation(
        relation_name=K8S_SERVICE_INFO_RELATION_NAME,
        remote_app=name,
        app_data=K8S_SERVICE_INFO_RELATION_DATA,
    )
    return rel_id
