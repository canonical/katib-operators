from contextlib import nullcontext as does_not_raise
from unittest.mock import MagicMock, patch

import pytest
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import CheckStatus
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
    assert harness.charm.model.unit.status == BlockedStatus(
        "Please add required database relation: eg. relational-db"
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
        "user": "user1",
    }
    harness.update_relation_data(rel_id, mysql_unit, data)
    with does_not_raise():
        harness.charm._get_db_data()


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
        "user": "user1",
    }
    harness.update_relation_data(rel_id, mysql_unit, data)
    harness.container_pebble_ready("katib-db-manager")
    pebble_plan = harness.get_container_pebble_plan("katib-db-manager")
    assert pebble_plan
    assert pebble_plan._services
    pebble_plan_info = pebble_plan.to_dict()
    assert pebble_plan_info["services"]["katib-db-manager"]["command"] == "./katib-db-manager"
    test_env = pebble_plan_info["services"]["katib-db-manager"]["environment"]
    # there should be size (6) environment variables
    assert 6 == len(test_env)


def test_apply_k8s_resources_success(
    harness, mocked_resource_handler, mocked_lightkube_client, mocked_kubernetes_service_patcher
):
    """Test if K8S resource handler is executed as expected."""
    harness.begin()
    harness.charm._apply_k8s_resources()
    mocked_resource_handler.apply.assert_called()
    assert isinstance(harness.charm.model.unit.status, MaintenanceStatus)


@patch("charm.KatibDBManagerOperator._get_check_status")
@pytest.mark.parametrize(
    "health_check_status, charm_status",
    [
        (CheckStatus.UP, ActiveStatus("")),
        (CheckStatus.DOWN, MaintenanceStatus("Workload failed health check")),
    ],
)
def test_update_status(
    _get_check_status: MagicMock,
    health_check_status,
    charm_status,
    harness,
    mocked_resource_handler,
    mocked_lightkube_client,
    mocked_kubernetes_service_patcher,
):
    """
    Test update status handler.
    Check on the correct charm status when health check status is UP/DOWN.
    """
    database = MagicMock()
    fetch_relation_data = MagicMock()
    fetch_relation_data.return_value = {
        "test-db-data": {
            "endpoints": "host:1234",
            "username": "username",
            "password": "password",
        }
    }
    database.fetch_relation_data = fetch_relation_data
    harness.model.get_relation = MagicMock(
        side_effect=_get_relation_db_only_side_effect_func
    )
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    harness.charm.database = database
    harness.container_pebble_ready("katib-db-manager")

    _get_check_status.return_value = health_check_status

    # test successful update status
    harness.charm.on.update_status.emit()
    assert harness.charm.model.unit.status == charm_status

def _get_relation_db_only_side_effect_func(relation):
    """Returns relational-db relation with some data."""
    if relation == "mysql":
        return None
    if relation == "relational-db":
        return {"some-data": True}

def test_relational_db_relation_no_data(
    harness, mocked_resource_handler, mocked_lightkube_client, mocked_kubernetes_service_patcher
):
    """Test that error is raised when relational-db has empty data."""
    database = MagicMock()
    fetch_relation_data = MagicMock()
    # setup empty data for library function to return
    fetch_relation_data.return_value = {}
    database.fetch_relation_data = fetch_relation_data
    harness.model.get_relation = MagicMock(
        side_effect=_get_relation_db_only_side_effect_func
    )
    harness.begin()
    harness.charm.database = database
    with pytest.raises(ErrorWithStatus) as err:
        harness.charm._get_db_data()
    assert err.value.status_type(WaitingStatus)
    assert "Waiting for relational-db data" in str(err)

def test_relational_db_relation_missing_attributes(
    harness, mocked_resource_handler, mocked_lightkube_client, mocked_kubernetes_service_patcher
):
    """Test that error is raised when relational-db has missing attributes data."""
    database = MagicMock()
    fetch_relation_data = MagicMock()
    # setup empty data for library function to return
    fetch_relation_data.return_value = {"test-db-data": {"password": "password1"}}
    database.fetch_relation_data = fetch_relation_data
    harness.model.get_relation = MagicMock(
        side_effect=_get_relation_db_only_side_effect_func
    )
    harness.begin()
    harness.charm.database = database
    with pytest.raises(ErrorWithStatus) as err:
        harness.charm._get_db_data()
    assert err.value.status_type(WaitingStatus)
    assert "Incorrect/incomplete data found in relation relational-db. See logs" in str(err)

def test_relational_db_relation_bad_data(
    harness, mocked_resource_handler, mocked_lightkube_client, mocked_kubernetes_service_patcher
):
    """Test that error is raised when relational-db has bad data."""
    database = MagicMock()
    fetch_relation_data = MagicMock()
    # setup bad data for library function to return
    fetch_relation_data.return_value = {"test-db-data": {"bad": "data"}}
    database.fetch_relation_data = fetch_relation_data
    harness.model.get_relation = MagicMock(
        side_effect=_get_relation_db_only_side_effect_func
    )
    harness.begin()
    harness.charm.database = database
    with pytest.raises(ErrorWithStatus) as err:
        harness.charm._get_db_data()
    assert err.value.status_type(WaitingStatus)
    assert "Incorrect/incomplete data found in relation relational-db. See logs" in str(err)

def test_relational_db_relation_with_data(
    harness, mocked_resource_handler, mocked_lightkube_client, mocked_kubernetes_service_patcher
):
    """Test that correct data is returned when data is in relational-db relation."""
    database = MagicMock()
    fetch_relation_data = MagicMock()
    fetch_relation_data.return_value = {
        "test-db-data": {
            "endpoints": "host:1234",
            "username": "username",
            "password": "password",
        }
    }
    database.fetch_relation_data = fetch_relation_data
    harness.model.get_relation = MagicMock(
        side_effect=_get_relation_db_only_side_effect_func
    )
    harness.begin()
    harness.charm.database = database
    res = harness.charm._get_db_data()
    for key, val in res.items():
        assert key, val in {
            "db_name": "mysql",
            "db_username": "username",
            "db_password": "password",
            "katib_db_host": "host",
            "katib_db_port": "1234",            
            "katib_db_name": "database",
        }
