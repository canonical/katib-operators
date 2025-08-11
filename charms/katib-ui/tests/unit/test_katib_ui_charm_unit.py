import pytest
from pytest_mock import mocker, MockerFixture
from ops.model import ActiveStatus

from ops.testing import Harness
from charm import KatibUIOperator


@pytest.fixture
def harness(mocker: MockerFixture):
    mocker.patch("charm.KubernetesServicePatch")
    harness = Harness(KatibUIOperator)
    harness.update_config({"port": 80})
    yield harness
    harness.cleanup()


def test_leader(mocker: MockerFixture, harness: Harness[KatibUIOperator]):
    check_container_conn = mocker.patch("charm.KatibUIOperator._check_container_connection")
    deploy_k8s_resources = mocker.patch("charm.KatibUIOperator._deploy_k8s_resources")

    # should do nothing if not leader
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    check_container_conn.assert_called()
    deploy_k8s_resources.assert_not_called()
    harness.cleanup()
    check_container_conn.reset_mock()
    deploy_k8s_resources.reset_mock()

    harness.set_leader(True)
    check_container_conn.assert_called()
    deploy_k8s_resources.assert_called()


def test_initial_plan(mocker: MockerFixture, harness: Harness[KatibUIOperator]):
    # mocks unrelated HTTP calls
    mocker.patch("charm.KatibUIOperator._deploy_k8s_resources")

    harness.set_leader(True)
    harness.begin()
    harness.container_pebble_ready("katib-ui")
    plan = harness.get_container_pebble_plan("katib-ui")
    expected_plan = {
        "services": {
            "katib-ui": {
                "override": "replace",
                "summary": "entrypoint of the katib-ui-operator image",
                "command": f"./katib-ui --port=80",
                "startup": "enabled",
                "environment": {"KATIB_CORE_NAMESPACE": harness.model.name},
            }
        }
    }
    assert plan.to_dict() == expected_plan
    assert isinstance(harness.charm.unit.status, ActiveStatus)
