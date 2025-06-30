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
    deploy_and_assert_grafana_agent,
    get_alert_rules,
)
from charms_dependencies import KATIB_DB_MANAGER
from lightkube.resources.core_v1 import ConfigMap
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
KATIB_CONFIG = "katib-config"
KATIB_VERSION = "v0.18.0"
TRIAL_TEMPLATE = "trial-template"
EXPECTED_TRIAL_TEMPLATE = {
    "defaultTrialTemplate.yaml": 'apiVersion: batch/v1\nkind: Job\nspec:\n  template:\n    spec:\n      containers:\n        - name: training-container\n          image: docker.io/ubuntu:22.04\n          command:\n            - "python3"\n            - "/opt/some-script.py"\n            - "--batch-size=64"\n            - "--lr=${trialParameters.learningRate}"\n            - "--num-layers=${trialParameters.numberLayers}"\n            - "--optimizer=${trialParameters.optimizer}"\n      restartPolicy: Never',  # noqa: E501
    "enasCPUTemplate": 'apiVersion: batch/v1\nkind: Job\nspec:\n  template:\n    spec:\n      containers:\n        - name: training-container\n          image: ghcr.io/kubeflow/katib/enas-cnn-cifar10-cpu:%(katib_version)s\n          command:\n            - python3\n            - -u\n            - RunTrial.py\n            - --num_epochs=1\n            - "--architecture=\\"${trialParameters.neuralNetworkArchitecture}\\""\n            - "--nn_config=\\"${trialParameters.neuralNetworkConfig}\\""\n      restartPolicy: Never'  # noqa: E501
    % {"katib_version": KATIB_VERSION},
    "pytorchJobTemplate": 'apiVersion: kubeflow.org/v1\nkind: PyTorchJob\nspec:\n  pytorchReplicaSpecs:\n    Master:\n      replicas: 1\n      restartPolicy: OnFailure\n      template:\n        spec:\n          containers:\n            - name: pytorch\n              image: ghcr.io/kubeflow/katib/pytorch-mnist-cpu:%(katib_version)s\n              command:\n                - "python3"\n                - "/opt/pytorch-mnist/mnist.py"\n                - "--epochs=1"\n                - "--lr=${trialParameters.learningRate}"\n                - "--momentum=${trialParameters.momentum}"\n    Worker:\n      replicas: 2\n      restartPolicy: OnFailure\n      template:\n        spec:\n          containers:\n            - name: pytorch\n              image: ghcr.io/kubeflow/katib/pytorch-mnist-cpu:%(katib_version)s\n              command:\n                - "python3"\n                - "/opt/pytorch-mnist/mnist.py"\n                - "--epochs=1"\n                - "--lr=${trialParameters.learningRate}"\n                - "--momentum=${trialParameters.momentum}"'  # noqa: E501
    % {"katib_version": KATIB_VERSION},
}
EXPECTED_TRIAL_TEMPLATE_CHANGED = {
    "defaultTrialTemplate.yaml": 'apiVersion: batch/v1\nkind: Job\nspec:\n  template:\n    spec:\n      containers:\n        - name: training-container\n          image: custom:1.0\n          command:\n            - "python3"\n            - "/opt/some-script.py"\n            - "--batch-size=64"\n            - "--lr=${trialParameters.learningRate}"\n            - "--num-layers=${trialParameters.numberLayers}"\n            - "--optimizer=${trialParameters.optimizer}"\n      restartPolicy: Never',  # noqa: E501
    "enasCPUTemplate": 'apiVersion: batch/v1\nkind: Job\nspec:\n  template:\n    spec:\n      containers:\n        - name: training-container\n          image: ghcr.io/kubeflow/katib/enas-cnn-cifar10-cpu:%(katib_version)s\n          command:\n            - python3\n            - -u\n            - RunTrial.py\n            - --num_epochs=1\n            - "--architecture=\\"${trialParameters.neuralNetworkArchitecture}\\""\n            - "--nn_config=\\"${trialParameters.neuralNetworkConfig}\\""\n      restartPolicy: Never'  # noqa: E501
    % {"katib_version": KATIB_VERSION},
    "pytorchJobTemplate": 'apiVersion: kubeflow.org/v1\nkind: PyTorchJob\nspec:\n  pytorchReplicaSpecs:\n    Master:\n      replicas: 1\n      restartPolicy: OnFailure\n      template:\n        spec:\n          containers:\n            - name: pytorch\n              image: ghcr.io/kubeflow/katib/pytorch-mnist-cpu:%(katib_version)s\n              command:\n                - "python3"\n                - "/opt/pytorch-mnist/mnist.py"\n                - "--epochs=1"\n                - "--lr=${trialParameters.learningRate}"\n                - "--momentum=${trialParameters.momentum}"\n    Worker:\n      replicas: 2\n      restartPolicy: OnFailure\n      template:\n        spec:\n          containers:\n            - name: pytorch\n              image: ghcr.io/kubeflow/katib/pytorch-mnist-cpu:%(katib_version)s\n              command:\n                - "python3"\n                - "/opt/pytorch-mnist/mnist.py"\n                - "--epochs=1"\n                - "--lr=${trialParameters.learningRate}"\n                - "--momentum=${trialParameters.momentum}"'  # noqa: E501
    % {"katib_version": KATIB_VERSION},
}

CUSTOM_IMAGES_PATH = (
    Path(__file__).resolve().parent.parent.parent / "src" / "default-custom-images.json"
)
with CUSTOM_IMAGES_PATH.open() as f:
    CUSTOM_IMAGES = json.load(f)

EXPECTED_KATIB_CONFIG = {
    "katib-config.yaml": f"""---
apiVersion: config.kubeflow.org/v1beta1
kind: KatibConfig
init:
  controller:
    webhookPort: 443
    trialResources:
      - Job.v1.batch
      - TFJob.v1.kubeflow.org
      - PyTorchJob.v1.kubeflow.org
      - MPIJob.v1.kubeflow.org
      - XGBoostJob.v1.kubeflow.org
runtime:
  metricsCollectors:
    - kind: StdOut
      image: {CUSTOM_IMAGES["metrics_collector_sidecar__stdout"]}
    - kind: File
      image: {CUSTOM_IMAGES["metrics_collector_sidecar__file"]}
    - kind: TensorFlowEvent
      image: {CUSTOM_IMAGES["metrics_collector_sidecar__tensorflow_event"]}
      resources:
        limits:
          memory: 1Gi
  suggestions:
    - algorithmName: random
      image: {CUSTOM_IMAGES["suggestion__random"]}
    - algorithmName: tpe
      image: {CUSTOM_IMAGES["suggestion__tpe"]}
    - algorithmName: grid
      image: {CUSTOM_IMAGES["suggestion__grid"]}
    - algorithmName: hyperband
      image: {CUSTOM_IMAGES["suggestion__hyperband"]}
    - algorithmName: bayesianoptimization
      image: {CUSTOM_IMAGES["suggestion__bayesianoptimization"]}
    - algorithmName: cmaes
      image: {CUSTOM_IMAGES["suggestion__cmaes"]}
    - algorithmName: sobol
      image: {CUSTOM_IMAGES["suggestion__sobol"]}
    - algorithmName: multivariate-tpe
      image: {CUSTOM_IMAGES["suggestion__multivariate_tpe"]}
    - algorithmName: enas
      image: {CUSTOM_IMAGES["suggestion__enas"]}
      resources:
        limits:
          memory: 400Mi
    - algorithmName: darts
      image: {CUSTOM_IMAGES["suggestion__darts"]}
    - algorithmName: pbt
      image: {CUSTOM_IMAGES["suggestion__pbt"]}
      persistentVolumeClaimSpec:
        accessModes:
          - ReadWriteMany
        resources:
          requests:
            storage: 5Gi
  earlyStoppings:
    - algorithmName: medianstop
      image: {CUSTOM_IMAGES["early_stopping__medianstop"]}
"""
}

EXPECTED_KATIB_CONFIG_CHANGED = {
    "katib-config.yaml": EXPECTED_KATIB_CONFIG["katib-config.yaml"].replace(
        CUSTOM_IMAGES["early_stopping__medianstop"], "custom:2.1"
    )
}


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

        for key in EXPECTED_KATIB_CONFIG:
            assert (
                katib_config_cm.data.get(key, "").rstrip() == EXPECTED_KATIB_CONFIG[key].rstrip()
            ), f"Mismatch in katib config map key: {key}"

        for key in EXPECTED_TRIAL_TEMPLATE:
            assert (
                trial_template_cm.data.get(key, "").rstrip()
                == EXPECTED_TRIAL_TEMPLATE[key].rstrip()
            ), f"Mismatch in trial template key: {key}"

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

        for key in EXPECTED_KATIB_CONFIG_CHANGED:
            assert (
                katib_config_cm.data.get(key, "").rstrip()
                == EXPECTED_KATIB_CONFIG_CHANGED[key].rstrip()
            ), f"Mismatch in changed katib config map key: {key}"

        for key in EXPECTED_TRIAL_TEMPLATE_CHANGED:
            assert (
                trial_template_cm.data.get(key, "").rstrip()
                == EXPECTED_TRIAL_TEMPLATE_CHANGED[key].rstrip()
            ), f"Mismatch in changed trial template key: {key}"

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

    async def test_metrics_enpoint(self, ops_test: OpsTest):
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
