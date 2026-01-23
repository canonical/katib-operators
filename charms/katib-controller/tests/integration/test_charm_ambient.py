import json
import logging
from pathlib import Path

import lightkube
import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    assert_alert_rules,
    assert_logging,
    assert_metrics_endpoint,
    assert_security_context,
    deploy_and_assert_grafana_agent,
    deploy_and_integrate_service_mesh_charms,
    generate_container_securitycontext_map,
    get_alert_rules,
    get_pod_names,
)
from charms_dependencies import KATIB_DB_MANAGER
from jinja2 import Template
from lightkube import Client
from lightkube.resources.core_v1 import ConfigMap
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

CUSTOM_IMAGES_PATH = Path("./src/default-custom-images.json")
with CUSTOM_IMAGES_PATH.open() as f:
    custom_images = json.load(f)

CONFIGMAP_TEMPLATE_PATH = Path("./src/templates/katib-config-configmap.yaml.j2")
CONFIGMAP_WEBHOOK_PORT = "8443"
TRIAL_TEMPLATE_PATH = Path("./src/templates/defaultTrialTemplate.yaml.j2")

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)
KATIB_CONFIG = "katib-config"
TRIAL_TEMPLATE = "trial-template"

configmap_context = {
    **custom_images,
    "webhookPort": CONFIGMAP_WEBHOOK_PORT,
}
trial_context = custom_images


def populate_template(template_path, context):
    """Populates a YAML template with values from the provided context.

    Args:
        template_path (str): Path to the YAML file that serves as the Jinja2 template.
        context (dict): Dictionary of values to render into the template.

    Returns:
        dict: The rendered YAML content as a Python dictionary.
    """
    with open(template_path, "r") as f:
        template = f.read()

    populated_template = Template(template).render(context)
    populated_template_yaml = yaml.safe_load(populated_template)

    return populated_template_yaml


@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    client = lightkube.Client(field_manager=CHARM_NAME)
    return client


class TestCharm:
    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest, request):
        """Build and deploy the charm.

        Assert on the unit status.
        """
        # Deploy dependency katib-db-manager
        await ops_test.model.deploy(
            KATIB_DB_MANAGER.charm, channel=KATIB_DB_MANAGER.channel, trust=KATIB_DB_MANAGER.trust
        )

        entity_url = (
            await ops_test.build_charm(".")
            if not (entity_url := request.config.getoption("--charm-path"))
            else entity_url
        )
        image_path = METADATA["resources"]["oci-image"]["upstream-source"]
        resources = {"oci-image": image_path}

        logger.info(entity_url)
        await ops_test.model.deploy(
            entity_url=entity_url,
            resources=resources,
            application_name=CHARM_NAME,
            trust=True,
        )
        await ops_test.model.integrate(CHARM_NAME, KATIB_DB_MANAGER.charm)
        await deploy_and_integrate_service_mesh_charms(
            CHARM_NAME, ops_test.model, relate_to_ingress_route_endpoint=False
        )

        await ops_test.model.wait_for_idle(apps=[CHARM_NAME], status="active", timeout=300)

        # Deploying grafana-agent-k8s and add all relations
        await deploy_and_assert_grafana_agent(
            ops_test.model, CHARM_NAME, metrics=True, dashboard=True, logging=True
        )

    async def test_configmap_created(self, lightkube_client: lightkube.Client, ops_test: OpsTest):
        """Test ConfigMaps are created with expected default values.

        NOTE: ConfigMap string values may differ only by trailing newlines,
        depending on how Kubernetes or the client library serializes YAML content.
        To avoid problems, we strip trailing whitespace from both sides.
        """
        katib_config_cm = lightkube_client.get(
            ConfigMap, KATIB_CONFIG, namespace=ops_test.model_name
        )
        trial_template_cm = lightkube_client.get(
            ConfigMap, TRIAL_TEMPLATE, namespace=ops_test.model_name
        )

        trial_context["namespace"] = ops_test.model_name
        expected_config = populate_template(CONFIGMAP_TEMPLATE_PATH, configmap_context)
        expected_trial_template = populate_template(TRIAL_TEMPLATE_PATH, trial_context)
        assert katib_config_cm.data == expected_config["data"]
        assert trial_template_cm.data == expected_trial_template["data"]

    async def test_configmap_changes_with_config(
        self, lightkube_client: lightkube.Client, ops_test: OpsTest
    ):
        """Test that config map values are updated when custom config is applied.

        NOTE: Like above, trailing newlines may differ in generated vs expected strings.
        Comparisons are done using `.rstrip()` to avoid superficial failures.
        """
        await ops_test.model.applications[CHARM_NAME].set_config(
            {
                "custom_images": '{"default_trial_template": "custom:1.0", "early_stopping__medianstop": "custom:2.1"}'  # noqa: E501
            }
        )
        await ops_test.model.wait_for_idle(
            apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=300
        )

        katib_config_cm = lightkube_client.get(
            ConfigMap, KATIB_CONFIG, namespace=ops_test.model_name
        )
        trial_template_cm = lightkube_client.get(
            ConfigMap, TRIAL_TEMPLATE, namespace=ops_test.model_name
        )

        trial_context["namespace"] = ops_test.model_name
        trial_context["default_trial_template"] = "custom:1.0"
        configmap_context["early_stopping__medianstop"] = "custom:2.1"

        expected_config = populate_template(CONFIGMAP_TEMPLATE_PATH, configmap_context)
        expected_trial_template = populate_template(TRIAL_TEMPLATE_PATH, trial_context)
        assert katib_config_cm.data == expected_config["data"]
        assert trial_template_cm.data == expected_trial_template["data"]

    async def test_blocked_on_invalid_config(self, ops_test: OpsTest):
        await ops_test.model.applications[CHARM_NAME].set_config({"custom_images": "{"})
        await ops_test.model.wait_for_idle(
            apps=[CHARM_NAME], status="blocked", raise_on_blocked=False, timeout=300
        )
        assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "blocked"

    async def test_alert_rules(self, ops_test: OpsTest):
        """Test check charm alert rules and rules defined in relation data bag."""
        app = ops_test.model.applications[CHARM_NAME]
        alert_rules = get_alert_rules()
        logger.info("found alert_rules: %s", alert_rules)
        await assert_alert_rules(app, alert_rules)

    async def test_metrics_endpoint(self, ops_test: OpsTest):
        """Test metrics_endpoints are defined in relation data bag and their accessibility.

        This function gets all the metrics_endpoints from the relation data bag, checks if
        they are available from the grafana-agent-k8s charm and finally compares them with the
        ones provided to the function.
        """
        app = ops_test.model.applications[CHARM_NAME]
        await assert_metrics_endpoint(app, metrics_port=8080, metrics_path="/metrics")

    async def test_logging(self, ops_test: OpsTest):
        """Test logging is defined in relation data bag."""
        app = ops_test.model.applications[GRAFANA_AGENT_APP]
        await assert_logging(app)

    @pytest.mark.parametrize("container_name", list(CONTAINERS_SECURITY_CONTEXT_MAP.keys()))
    async def test_container_security_context(
        self,
        ops_test: OpsTest,
        lightkube_client: Client,
        container_name: str,
    ):
        """Test container security context is correctly set.

        Verify that container spec defines the security context with correct
        user ID and group ID.
        """
        pod_name = get_pod_names(ops_test.model.name, CHARM_NAME)[0]
        assert_security_context(
            lightkube_client,
            pod_name,
            container_name,
            CONTAINERS_SECURITY_CONTEXT_MAP,
            ops_test.model.name,
        )
