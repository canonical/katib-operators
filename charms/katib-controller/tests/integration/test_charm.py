from pathlib import Path

import lightkube
import pytest
import yaml
from lightkube.resources.core_v1 import ConfigMap
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
KATIB_CONFIG = "katib-config"
TRIAL_TEMPLATE = "trial-template"
EXPECTED_KATIB_CONFIG = {
    "early-stopping": '{\n  "medianstop": {\n    "image": "docker.io/kubeflowkatib/earlystopping-medianstop:v0.15.0"\n  }\n}',  # noqa: E501
    "metrics-collector-sidecar": '{\n  "StdOut": {\n    "image": "docker.io/kubeflowkatib/file-metrics-collector:v0.15.0"\n  },\n  "File": {\n    "image": "docker.io/kubeflowkatib/file-metrics-collector:v0.15.0"\n  },\n  "TensorFlowEvent": {\n    "image": "docker.io/kubeflowkatib/tfevent-metrics-collector:v0.15.0",\n    "resources": {\n      "limits": {\n        "memory": "1Gi"\n      }\n    }\n  }\n}',  # noqa: E501
    "suggestion": '{\n  "random": {\n    "image": "docker.io/kubeflowkatib/suggestion-hyperopt:v0.15.0"\n  },\n  "tpe": {\n    "image": "docker.io/kubeflowkatib/suggestion-hyperopt:v0.15.0"\n  },\n  "grid": {\n    "image": "docker.io/kubeflowkatib/suggestion-optuna:v0.15.0"\n  },\n  "hyperband": {\n    "image": "docker.io/kubeflowkatib/suggestion-hyperband:v0.15.0"\n  },\n  "bayesianoptimization": {\n    "image": "docker.io/kubeflowkatib/suggestion-skopt:v0.15.0"\n  },\n  "cmaes": {\n    "image": "docker.io/kubeflowkatib/suggestion-goptuna:v0.15.0"\n  },\n  "sobol": {\n    "image": "docker.io/kubeflowkatib/suggestion-goptuna:v0.15.0"\n  },\n  "multivariate-tpe": {\n    "image": "docker.io/kubeflowkatib/suggestion-optuna:v0.15.0"\n  },\n  "enas": {\n    "image": "docker.io/kubeflowkatib/suggestion-enas:v0.15.0",\n    "resources": {\n      "limits": {\n        "memory": "200Mi"\n      }\n    }\n  },\n  "darts": {\n    "image": "docker.io/kubeflowkatib/suggestion-darts:v0.15.0"\n  },\n  "pbt": {\n    "image": "docker.io/kubeflowkatib/suggestion-pbt:v0.15.0",\n    "persistentVolumeClaimSpec": {\n      "accessModes": [\n        "ReadWriteMany"\n      ],\n      "resources": {\n        "requests": {\n          "storage": "5Gi"\n        }\n      }\n    }\n  }\n}',  # noqa: E501
}
EXPECTED_KATIB_CONFIG_CHANGED = {
    "early-stopping": '{\n  "medianstop": {\n    "image": "custom:2.1"\n  }\n}',  # noqa: E501
    "metrics-collector-sidecar": '{\n  "StdOut": {\n    "image": "docker.io/kubeflowkatib/file-metrics-collector:v0.15.0"\n  },\n  "File": {\n    "image": "docker.io/kubeflowkatib/file-metrics-collector:v0.15.0"\n  },\n  "TensorFlowEvent": {\n    "image": "docker.io/kubeflowkatib/tfevent-metrics-collector:v0.15.0",\n    "resources": {\n      "limits": {\n        "memory": "1Gi"\n      }\n    }\n  }\n}',  # noqa: E501
    "suggestion": '{\n  "random": {\n    "image": "docker.io/kubeflowkatib/suggestion-hyperopt:v0.15.0"\n  },\n  "tpe": {\n    "image": "docker.io/kubeflowkatib/suggestion-hyperopt:v0.15.0"\n  },\n  "grid": {\n    "image": "docker.io/kubeflowkatib/suggestion-optuna:v0.15.0"\n  },\n  "hyperband": {\n    "image": "docker.io/kubeflowkatib/suggestion-hyperband:v0.15.0"\n  },\n  "bayesianoptimization": {\n    "image": "docker.io/kubeflowkatib/suggestion-skopt:v0.15.0"\n  },\n  "cmaes": {\n    "image": "docker.io/kubeflowkatib/suggestion-goptuna:v0.15.0"\n  },\n  "sobol": {\n    "image": "docker.io/kubeflowkatib/suggestion-goptuna:v0.15.0"\n  },\n  "multivariate-tpe": {\n    "image": "docker.io/kubeflowkatib/suggestion-optuna:v0.15.0"\n  },\n  "enas": {\n    "image": "docker.io/kubeflowkatib/suggestion-enas:v0.15.0",\n    "resources": {\n      "limits": {\n        "memory": "200Mi"\n      }\n    }\n  },\n  "darts": {\n    "image": "docker.io/kubeflowkatib/suggestion-darts:v0.15.0"\n  },\n  "pbt": {\n    "image": "docker.io/kubeflowkatib/suggestion-pbt:v0.15.0",\n    "persistentVolumeClaimSpec": {\n      "accessModes": [\n        "ReadWriteMany"\n      ],\n      "resources": {\n        "requests": {\n          "storage": "5Gi"\n        }\n      }\n    }\n  }\n}',  # noqa: E501
}
EXPECTED_TRIAL_TEMPLATE = {
    "defaultTrialTemplate.yaml": 'apiVersion: batch/v1\nkind: Job\nspec:\n  template:\n    spec:\n      containers:\n        - name: training-container\n          image: docker.io/ubuntu:22.04\n          command:\n            - "python3"\n            - "/opt/some-script.py"\n            - "--batch-size=64"\n            - "--lr=${trialParameters.learningRate}"\n            - "--num-layers=${trialParameters.numberLayers}"\n            - "--optimizer=${trialParameters.optimizer}"\n      restartPolicy: Never',  # noqa: E501
}
EXPECTED_TRIAL_TEMPLATE_CHANGED = {
    "defaultTrialTemplate.yaml": 'apiVersion: batch/v1\nkind: Job\nspec:\n  template:\n    spec:\n      containers:\n        - name: training-container\n          image: custom:1.0\n          command:\n            - "python3"\n            - "/opt/some-script.py"\n            - "--batch-size=64"\n            - "--lr=${trialParameters.learningRate}"\n            - "--num-layers=${trialParameters.numberLayers}"\n            - "--optimizer=${trialParameters.optimizer}"\n      restartPolicy: Never',  # noqa: E501
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
        charm_under_test = await ops_test.build_charm(".")
        image_path = METADATA["resources"]["oci-image"]["upstream-source"]
        resources = {"oci-image": image_path}

        await ops_test.model.deploy(
            charm_under_test, resources=resources, application_name=CHARM_NAME
        )

        await ops_test.model.wait_for_idle(
            apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=300
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
