from contextlib import nullcontext as does_not_raise
from unittest.mock import MagicMock

import pytest
from ops.model import MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import KatibDBManagerOperator


@pytest.fixture
def harness():
    """Returns a harnessed charm with leader == True."""
    harness = Harness(KatibDBManagerOperator)
    harness.set_leader(True)
    return harness


@pytest.fixture()
def mocked_resource_handler(mocker):
    """Yields a mocked resource handler."""
    mocked_resource_handler = MagicMock()
    mocked_resource_handler_factory = mocker.patch("charm.KubernetesResourceHandler")
    mocked_resource_handler_factory.return_value = mocked_resource_handler
    yield mocked_resource_handler


@pytest.fixture()
def mocked_lightkube_client(mocker, mocked_resource_handler):
    """Prevents lightkube clients from being created, returning a mock instead."""
    mocked_resource_handler.lightkube_client = MagicMock()
    yield mocked_resource_handler.lightkube_client


@pytest.fixture()
def mocked_kubernetes_service_patcher(mocker):
    mocked_service_patcher = mocker.patch("charm.KubernetesServicePatch")
    mocked_service_patcher.return_value = lambda x, y: None
    yield mocked_service_patcher


def test_not_leader(
    harness, mocked_resource_handler, mocked_lightkube_client, mocked_kubernetes_service_patcher
):
    """Test that charm waits if not leader."""
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("katib-db-manager")
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_no_relation(
    harness, mocked_resource_handler, mocked_lightkube_client, mocked_kubernetes_service_patcher
):
    """Test no relation scenario."""
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("katib-db-manager")
    assert harness.charm.model.unit.status == WaitingStatus(
        "Waiting for mysql connection information"
    )


def test_mysql_relation(
    harness, mocked_resource_handler, mocked_lightkube_client, mocked_kubernetes_service_patcher
):
    "Test that no error is raised when mysql complete relation exists."
    harness.begin()

    mysql_app = "mysql_app"
    mysql_unit = f"{mysql_app}/0"

    rel_id = harness.add_relation("mysql", mysql_app)
    harness.add_relation_unit(rel_id, mysql_unit)

    # Test complete relation
    data = {
        "database": "database",
        "host": "host",
        "root_password": "root_password",
        "port": "port",
    }
    harness.update_relation_data(rel_id, mysql_unit, data)
    with does_not_raise():
        harness.charm._check_mysql()


def test_pebble_layer(
    harness, mocked_resource_handler, mocked_lightkube_client, mocked_kubernetes_service_patcher
):
    """
    Test creation of Pebble layer given that mysql relation is complete.
    Only testing specific items.
    """
    harness.set_model_name("test_kubeflow")
    harness.begin_with_initial_hooks()
    mysql_app = "mysql_app"
    mysql_unit = f"{mysql_app}/0"

    rel_id = harness.add_relation("mysql", mysql_app)
    harness.add_relation_unit(rel_id, mysql_unit)

    # Test complete relation
    data = {
        "database": "database",
        "host": "host",
        "root_password": "root_password",
        "port": "port",
    }
    harness.update_relation_data(rel_id, mysql_unit, data)
    harness.container_pebble_ready("katib-db-manager")
    pebble_plan = harness.get_container_pebble_plan("katib-db-manager")
    assert pebble_plan
    assert pebble_plan._services
    pebble_plan_info = pebble_plan.to_dict()
    assert pebble_plan_info["services"]["katib-db-manager"]["command"] == "./katib-db-manager"
    test_env = pebble_plan_info["services"]["katib-db-manager"]["environment"]
    assert 6 == len(test_env)


def test_apply_k8s_resources_success(
    harness, mocked_resource_handler, mocked_lightkube_client, mocked_kubernetes_service_patcher
):
    """Test if K8S resource handler is executed as expected."""
    harness.begin()
    harness.charm._apply_k8s_resources()
    mocked_resource_handler.apply.assert_called()
    assert isinstance(harness.charm.model.unit.status, MaintenanceStatus)
