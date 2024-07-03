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
from lightkube.resources.core_v1 import ConfigMap
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
KATIB_CONFIG = "katib-config"
KATIB_DB_MANAGER = "katib-db-manager"
KATIB_DB_MANAGER_CHANNEL = "latest/edge"
TRIAL_TEMPLATE = "trial-template"
EXPECTED_KATIB_CONFIG = {
    "katib-config.yaml": "---\napiVersion: config.kubeflow.org/v1beta1\nkind: KatibConfig\ninit:\n  controller:\n    webhookPort: 443\n    trialResources:\n      - Job.v1.batch\n      - TFJob.v1.kubeflow.org\n      - PyTorchJob.v1.kubeflow.org\n      - MPIJob.v1.kubeflow.org\n      - XGBoostJob.v1.kubeflow.org\n      - MXJob.v1.kubeflow.org\nruntime:\n  metricsCollectors:\n    - kind: StdOut\n      image: docker.io/kubeflowkatib/file-metrics-collector:v0.17.0-rc.1\n    - kind: File\n      image: docker.io/kubeflowkatib/file-metrics-collector:v0.17.0-rc.1\n    - kind: TensorFlowEvent\n      image: docker.io/kubeflowkatib/tfevent-metrics-collector:v0.17.0-rc.1\n      resources:\n        limits:\n          memory: 1Gi\n  suggestions:\n    - algorithmName: random\n      image: docker.io/kubeflowkatib/suggestion-hyperopt:v0.17.0-rc.1\n    - algorithmName: tpe\n      image: docker.io/kubeflowkatib/suggestion-hyperopt:v0.17.0-rc.1\n    - algorithmName: grid\n      image: docker.io/kubeflowkatib/suggestion-optuna:v0.17.0-rc.1\n    - algorithmName: hyperband\n      image: docker.io/kubeflowkatib/suggestion-hyperband:v0.17.0-rc.1\n    - algorithmName: bayesianoptimization\n      image: docker.io/kubeflowkatib/suggestion-skopt:v0.17.0-rc.1\n    - algorithmName: cmaes\n      image: docker.io/kubeflowkatib/suggestion-goptuna:v0.17.0-rc.1\n    - algorithmName: sobol\n      image: docker.io/kubeflowkatib/suggestion-goptuna:v0.17.0-rc.1\n    - algorithmName: multivariate-tpe\n      image: docker.io/kubeflowkatib/suggestion-optuna:v0.17.0-rc.1\n    - algorithmName: enas\n      image: docker.io/kubeflowkatib/suggestion-enas:v0.17.0-rc.1\n      resources:\n        limits:\n          memory: 400Mi\n    - algorithmName: darts\n      image: docker.io/kubeflowkatib/suggestion-darts:v0.17.0-rc.1\n    - algorithmName: pbt\n      image: docker.io/kubeflowkatib/suggestion-pbt:v0.17.0-rc.1\n      persistentVolumeClaimSpec:\n        accessModes:\n          - ReadWriteMany\n        resources:\n          requests:\n            storage: 5Gi\n  earlyStoppings:\n    - algorithmName: medianstop\n      image: docker.io/kubeflowkatib/earlystopping-medianstop:v0.17.0-rc.1",  # noqa: E501
}
EXPECTED_KATIB_CONFIG_CHANGED = {
    "katib-config.yaml": "---\napiVersion: config.kubeflow.org/v1beta1\nkind: KatibConfig\ninit:\n  controller:\n    webhookPort: 443\n    trialResources:\n      - Job.v1.batch\n      - TFJob.v1.kubeflow.org\n      - PyTorchJob.v1.kubeflow.org\n      - MPIJob.v1.kubeflow.org\n      - XGBoostJob.v1.kubeflow.org\n      - MXJob.v1.kubeflow.org\nruntime:\n  metricsCollectors:\n    - kind: StdOut\n      image: docker.io/kubeflowkatib/file-metrics-collector:v0.17.0-rc.1\n    - kind: File\n      image: docker.io/kubeflowkatib/file-metrics-collector:v0.17.0-rc.1\n    - kind: TensorFlowEvent\n      image: docker.io/kubeflowkatib/tfevent-metrics-collector:v0.17.0-rc.1\n      resources:\n        limits:\n          memory: 1Gi\n  suggestions:\n    - algorithmName: random\n      image: docker.io/kubeflowkatib/suggestion-hyperopt:v0.17.0-rc.1\n    - algorithmName: tpe\n      image: docker.io/kubeflowkatib/suggestion-hyperopt:v0.17.0-rc.1\n    - algorithmName: grid\n      image: docker.io/kubeflowkatib/suggestion-optuna:v0.17.0-rc.1\n    - algorithmName: hyperband\n      image: docker.io/kubeflowkatib/suggestion-hyperband:v0.17.0-rc.1\n    - algorithmName: bayesianoptimization\n      image: docker.io/kubeflowkatib/suggestion-skopt:v0.17.0-rc.1\n    - algorithmName: cmaes\n      image: docker.io/kubeflowkatib/suggestion-goptuna:v0.17.0-rc.1\n    - algorithmName: sobol\n      image: docker.io/kubeflowkatib/suggestion-goptuna:v0.17.0-rc.1\n    - algorithmName: multivariate-tpe\n      image: docker.io/kubeflowkatib/suggestion-optuna:v0.17.0-rc.1\n    - algorithmName: enas\n      image: docker.io/kubeflowkatib/suggestion-enas:v0.17.0-rc.1\n      resources:\n        limits:\n          memory: 400Mi\n    - algorithmName: darts\n      image: docker.io/kubeflowkatib/suggestion-darts:v0.17.0-rc.1\n    - algorithmName: pbt\n      image: docker.io/kubeflowkatib/suggestion-pbt:v0.17.0-rc.1\n      persistentVolumeClaimSpec:\n        accessModes:\n          - ReadWriteMany\n        resources:\n          requests:\n            storage: 5Gi\n  earlyStoppings:\n    - algorithmName: medianstop\n      image: custom:2.1",  # noqa: E501
}
EXPECTED_TRIAL_TEMPLATE = {
    "defaultTrialTemplate.yaml": 'apiVersion: batch/v1\nkind: Job\nspec:\n  template:\n    spec:\n      containers:\n        - name: training-container\n          image: docker.io/ubuntu:22.04\n          command:\n            - "python3"\n            - "/opt/some-script.py"\n            - "--batch-size=64"\n            - "--lr=${trialParameters.learningRate}"\n            - "--num-layers=${trialParameters.numberLayers}"\n            - "--optimizer=${trialParameters.optimizer}"\n      restartPolicy: Never',  # noqa: E501
    "enasCPUTemplate": 'apiVersion: batch/v1\nkind: Job\nspec:\n  template:\n    spec:\n      containers:\n        - name: training-container\n          image: docker.io/kubeflowkatib/enas-cnn-cifar10-cpu:v0.17.0-rc.1\n          command:\n            - python3\n            - -u\n            - RunTrial.py\n            - --num_epochs=1\n            - "--architecture=\\"${trialParameters.neuralNetworkArchitecture}\\""\n            - "--nn_config=\\"${trialParameters.neuralNetworkConfig}\\""\n      restartPolicy: Never',  # noqa: E501
    "pytorchJobTemplate": 'apiVersion: kubeflow.org/v1\nkind: PyTorchJob\nspec:\n  pytorchReplicaSpecs:\n    Master:\n      replicas: 1\n      restartPolicy: OnFailure\n      template:\n        spec:\n          containers:\n            - name: pytorch\n              image: docker.io/kubeflowkatib/pytorch-mnist-cpu:v0.17.0-rc.1\n              command:\n                - "python3"\n                - "/opt/pytorch-mnist/mnist.py"\n                - "--epochs=1"\n                - "--lr=${trialParameters.learningRate}"\n                - "--momentum=${trialParameters.momentum}"\n    Worker:\n      replicas: 2\n      restartPolicy: OnFailure\n      template:\n        spec:\n          containers:\n            - name: pytorch\n              image: docker.io/kubeflowkatib/pytorch-mnist-cpu:v0.17.0-rc.1\n              command:\n                - "python3"\n                - "/opt/pytorch-mnist/mnist.py"\n                - "--epochs=1"\n                - "--lr=${trialParameters.learningRate}"\n                - "--momentum=${trialParameters.momentum}"',  # noqa: E501
}
EXPECTED_TRIAL_TEMPLATE_CHANGED = {
    "defaultTrialTemplate.yaml": 'apiVersion: batch/v1\nkind: Job\nspec:\n  template:\n    spec:\n      containers:\n        - name: training-container\n          image: custom:1.0\n          command:\n            - "python3"\n            - "/opt/some-script.py"\n            - "--batch-size=64"\n            - "--lr=${trialParameters.learningRate}"\n            - "--num-layers=${trialParameters.numberLayers}"\n            - "--optimizer=${trialParameters.optimizer}"\n      restartPolicy: Never',  # noqa: E501
    "enasCPUTemplate": 'apiVersion: batch/v1\nkind: Job\nspec:\n  template:\n    spec:\n      containers:\n        - name: training-container\n          image: docker.io/kubeflowkatib/enas-cnn-cifar10-cpu:v0.17.0-rc.1\n          command:\n            - python3\n            - -u\n            - RunTrial.py\n            - --num_epochs=1\n            - "--architecture=\\"${trialParameters.neuralNetworkArchitecture}\\""\n            - "--nn_config=\\"${trialParameters.neuralNetworkConfig}\\""\n      restartPolicy: Never',  # noqa: E501
    "pytorchJobTemplate": 'apiVersion: kubeflow.org/v1\nkind: PyTorchJob\nspec:\n  pytorchReplicaSpecs:\n    Master:\n      replicas: 1\n      restartPolicy: OnFailure\n      template:\n        spec:\n          containers:\n            - name: pytorch\n              image: docker.io/kubeflowkatib/pytorch-mnist-cpu:v0.17.0-rc.1\n              command:\n                - "python3"\n                - "/opt/pytorch-mnist/mnist.py"\n                - "--epochs=1"\n                - "--lr=${trialParameters.learningRate}"\n                - "--momentum=${trialParameters.momentum}"\n    Worker:\n      replicas: 2\n      restartPolicy: OnFailure\n      template:\n        spec:\n          containers:\n            - name: pytorch\n              image: docker.io/kubeflowkatib/pytorch-mnist-cpu:v0.17.0-rc.1\n              command:\n                - "python3"\n                - "/opt/pytorch-mnist/mnist.py"\n                - "--epochs=1"\n                - "--lr=${trialParameters.learningRate}"\n                - "--momentum=${trialParameters.momentum}"',  # noqa: E501
}


@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    client = lightkube.Client(field_manager=CHARM_NAME)
    return client


class TestCharm:
    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest):
        """Build and deploy the charm.

        Assert on the unit status.
        """
        # Deploy dependency katib-db-manager
        await ops_test.model.deploy(KATIB_DB_MANAGER, channel=KATIB_DB_MANAGER_CHANNEL, trust=True)

        charm_under_test = await ops_test.build_charm(".")
        image_path = METADATA["resources"]["oci-image"]["upstream-source"]
        resources = {"oci-image": image_path}

        await ops_test.model.deploy(
            charm_under_test,
            resources=resources,
            application_name=CHARM_NAME,
            trust=True,
        )
        await ops_test.model.integrate(CHARM_NAME, KATIB_DB_MANAGER)

        await ops_test.model.wait_for_idle(apps=[CHARM_NAME], status="active", timeout=300)

        # Deploying grafana-agent-k8s and add all relations
        await deploy_and_assert_grafana_agent(
            ops_test.model, CHARM_NAME, metrics=True, dashboard=True, logging=True
        )

    async def test_configmap_created(self, lightkube_client: lightkube.Client, ops_test: OpsTest):
        """Test configmaps contents with default coonfig."""
        katib_config_cm = lightkube_client.get(
            ConfigMap, KATIB_CONFIG, namespace=ops_test.model_name
        )
        trial_template_cm = lightkube_client.get(
            ConfigMap, TRIAL_TEMPLATE, namespace=ops_test.model_name
        )

        assert katib_config_cm.data == EXPECTED_KATIB_CONFIG
        assert trial_template_cm.data == EXPECTED_TRIAL_TEMPLATE

    async def test_configmap_changes_with_config(
        self, lightkube_client: lightkube.Client, ops_test: OpsTest
    ):
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

        assert katib_config_cm.data == EXPECTED_KATIB_CONFIG_CHANGED
        assert trial_template_cm.data == EXPECTED_TRIAL_TEMPLATE_CHANGED

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
