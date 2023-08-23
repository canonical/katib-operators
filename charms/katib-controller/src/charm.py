#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from base64 import b64encode
from pathlib import Path
from subprocess import check_call
from typing import Dict

import yaml
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from jinja2 import Environment, FileSystemLoader, Template
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

DEFAULT_IMAGES = {
    "default_trial_template": "docker.io/kubeflowkatib/mxnet-mnist:v0.16.0-rc.1",
    "early_stopping__medianstop": "docker.io/kubeflowkatib/earlystopping-medianstop:v0.16.0-rc.1",
    "enas_cpu_template": "docker.io/kubeflowkatib/enas-cnn-cifar10-cpu:v0.16.0-rc.1",
    "metrics_collector_sidecar__stdout": "docker.io/kubeflowkatib/file-metrics-collector:v0.16.0-rc.1",  # noqa: E501
    "metrics_collector_sidecar__file": "docker.io/kubeflowkatib/file-metrics-collector:v0.16.0-rc.1",  # noqa: E501
    "metrics_collector_sidecar__tensorflow_event": "docker.io/kubeflowkatib/tfevent-metrics-collector:v0.16.0-rc.1",  # noqa: E501
    "pytorch_job_template__master": "docker.io/kubeflowkatib/pytorch-mnist-cpu:v0.16.0-rc.1",
    "pytorch_job_template__worker": "docker.io/kubeflowkatib/pytorch-mnist-cpu:v0.16.0-rc.1",
    "suggestion__random": "docker.io/kubeflowkatib/suggestion-hyperopt:v0.16.0-rc.1",
    "suggestion__tpe": "docker.io/kubeflowkatib/suggestion-hyperopt:v0.16.0-rc.1",
    "suggestion__grid": "docker.io/kubeflowkatib/suggestion-optuna:v0.16.0-rc.1",
    "suggestion__hyperband": "docker.io/kubeflowkatib/suggestion-hyperband:v0.16.0-rc.1",
    "suggestion__bayesianoptimization": "docker.io/kubeflowkatib/suggestion-skopt:v0.16.0-rc.1",
    "suggestion__cmaes": "docker.io/kubeflowkatib/suggestion-goptuna:v0.16.0-rc.1",
    "suggestion__sobol": "docker.io/kubeflowkatib/suggestion-goptuna:v0.16.0-rc.1",
    "suggestion__multivariate_tpe": "docker.io/kubeflowkatib/suggestion-optuna:v0.16.0-rc.1",
    "suggestion__enas": "docker.io/kubeflowkatib/suggestion-enas:v0.16.0-rc.1",
    "suggestion__darts": "docker.io/kubeflowkatib/suggestion-darts:v0.16.0-rc.1",
    "suggestion__pbt": "docker.io/kubeflowkatib/suggestion-pbt:v0.16.0-rc.1",
}

logger = logging.getLogger(__name__)


def parse_images_config(config: str) -> Dict:
    """
    Parse a YAML config-defined images list.

    This function takes a YAML-formatted string 'config' containing a list of images
    and returns a dictionary representing the images.

    Args:
        config (str): YAML-formatted string representing a list of images.

    Returns:
        Dict: A list of images.
    """
    error_message = (
        f"Cannot parse a config-defined images list from config '{config}' - this"
        "config input will be ignored."
    )
    if not config:
        return []
    try:
        images = yaml.safe_load(config)
    except yaml.YAMLError as err:
        logger.warning(
            f"{error_message}  Got error: {err}, while parsing the custom_image config."
        )
        raise CheckFailed(error_message, BlockedStatus)
    return images


def render_template(template_path: str, context: Dict) -> str:
    """
    Render a Jinja2 template.

    This function takes the file path of a Jinja2 template and a context dictionary
    containing the variables for template rendering. It loads the template,
    substitutes the variables in the context, and returns the rendered content.

    Args:
        template_path (str): The file path of the Jinja2 template.
        context (Dict): A dictionary containing the variables for template rendering.

    Returns:
        str: The rendered template content.
    """
    template = Template(Path(template_path).read_text())
    rendered_template = template.render(**context)
    return rendered_template


class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


class Operator(CharmBase):
    """Deploys the katib-controller service."""

    _stored = StoredState()

    def __init__(self, framework):
        super().__init__(framework)

        self._stored.set_default(**self.gen_certs())
        self.image = OCIImageResource(self, "oci-image")
        self.custom_images = []
        self.images_context = {}
        self.env = Environment(loader=FileSystemLoader("src/"))

        self.prometheus_provider = MetricsEndpointProvider(
            charm=self,
            jobs=[
                {
                    "job_name": "katib_controller_metrics",
                    "static_configs": [{"targets": [f"*:{self.config['metrics-port']}"]}],
                }
            ],
        )
        self.dashboard_provider = GrafanaDashboardProvider(self)

        for event in [
            self.on.config_changed,
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
        ]:
            self.framework.observe(event, self.set_pod_spec)

    def get_images(
        self, default_images: Dict[str, str], custom_images: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Combine default images with custom images.

        This function takes two dictionaries, 'default_images' and 'custom_images',
        representing the default set of images and the custom set of images respectively.
        It combines the custom images into the default image list, overriding any matching
        image names from the default list with the custom ones.

        Args:
            default_images (Dict[str, str]): A dictionary containing the default image names
                as keys and their corresponding default image URIs as values.
            custom_images (Dict[str, str]): A dictionary containing the custom image names
                as keys and their corresponding custom image URIs as values.

        Returns:
            Dict[str, str]: A dictionary representing the combined images, where image names
            from the custom_images override any matching image names from the default_images.
        """
        images = default_images
        for image_name, custom_image in custom_images.items():
            if custom_image:
                if image_name in images:
                    images[image_name] = custom_image
                else:
                    logger.warning(f"image_name {image_name} not in image list, ignoring.")
        return images

    def set_pod_spec(self, event):
        self.model.unit.status = MaintenanceStatus("Setting pod spec")

        try:
            self._check_leader()
            self.custom_images = parse_images_config(self.model.config["custom_images"])
            self.images_context = self.get_images(DEFAULT_IMAGES, self.custom_images)
            self.katib_config_context = self.images_context
            self.katib_config_context["webhookPort"] = self.model.config["webhook-port"]
            image_details = self._check_image_details()
        except CheckFailed as check_failed:
            self.model.unit.status = check_failed.status
            return

        validating, mutating = self._rendered_webhook_definitions()

        self.model.pod.set_spec(
            {
                "version": 3,
                "serviceAccount": {
                    "roles": [
                        {
                            "global": True,
                            "rules": [
                                {
                                    "apiGroups": [""],
                                    "resources": [
                                        "configmaps",
                                        "serviceaccounts",
                                        "services",
                                        "events",
                                        "namespaces",
                                        "persistentvolumes",
                                        "persistentvolumeclaims",
                                        "pods",
                                        "pods/log",
                                        "pods/status",
                                        "secrets",
                                    ],
                                    "verbs": ["*"],
                                },
                                {
                                    "apiGroups": ["apps"],
                                    "resources": ["deployments"],
                                    "verbs": ["*"],
                                },
                                {
                                    "apiGroups": ["rbac.authorization.k8s.io"],
                                    "resources": ["roles", "rolebindings"],
                                    "verbs": ["*"],
                                },
                                {
                                    "apiGroups": ["batch"],
                                    "resources": ["jobs", "cronjobs"],
                                    "verbs": ["*"],
                                },
                                {
                                    "apiGroups": ["kubeflow.org"],
                                    "resources": [
                                        "experiments",
                                        "experiments/status",
                                        "experiments/finalizers",
                                        "trials",
                                        "trials/status",
                                        "trials/finalizers",
                                        "suggestions",
                                        "suggestions/status",
                                        "suggestions/finalizers",
                                        "tfjobs",
                                        "pytorchjobs",
                                        "mpijobs",
                                        "xgboostjobs",
                                        "mxjobs",
                                    ],
                                    "verbs": ["*"],
                                },
                                {
                                    "apiGroups": ["admissionregistration.k8s.io"],
                                    "resources": [
                                        "validatingwebhookconfigurations",
                                        "mutatingwebhookconfigurations",
                                    ],
                                    "verbs": ["get", "watch", "list", "patch"],
                                },
                            ],
                        }
                    ]
                },
                "containers": [
                    {
                        "name": "katib-controller",
                        "imageDetails": image_details,
                        "command": ["./katib-controller"],
                        "args": ["--katib-config=/katib-config.yaml"],
                        "ports": [
                            {
                                "name": "webhook",
                                "containerPort": self.model.config["webhook-port"],
                            },
                            {
                                "name": "metrics",
                                "containerPort": self.model.config["metrics-port"],
                            },
                        ],
                        "envConfig": {"KATIB_CORE_NAMESPACE": self.model.name},
                        "volumeConfig": [
                            {
                                "name": "certs",
                                "mountPath": "/tmp/cert",
                                "files": [
                                    {"path": "ca.crt", "content": self._stored.ca},
                                    {"path": "tls.crt", "content": self._stored.cert},
                                    {"path": "tls.key", "content": self._stored.key},
                                ],
                            },
                            {
                                "name": "katib-config",
                                "mountPath": "/katib-config.yaml",
                                "subPath": "katib-config.yaml",
                            },
                        ],
                    }
                ],
            },
            k8s_resources={
                "kubernetesResources": {
                    "customResourceDefinitions": [
                        {"name": crd["metadata"]["name"], "spec": crd["spec"]}
                        for crd in yaml.safe_load_all(Path("src/crds.yaml").read_text())
                    ],
                    "mutatingWebhookConfigurations": [
                        {
                            "name": mutating["metadata"]["name"],
                            "webhooks": mutating["webhooks"],
                        }
                    ],
                    "validatingWebhookConfigurations": [
                        {
                            "name": validating["metadata"]["name"],
                            "webhooks": validating["webhooks"],
                        }
                    ],
                },
                "configMaps": {
                    "katib-config": {
                        "katib-config.yaml": render_template(
                            "src/templates/katib-config.yaml.j2", self.katib_config_context
                        )
                    },
                    "trial-template": {
                        f
                        + suffix: render_template(
                            f"src/templates/{f}.yaml.j2", self.images_context
                        )
                        for f, suffix in (
                            ("defaultTrialTemplate", ".yaml"),
                            ("enasCPUTemplate", ""),
                            ("pytorchJobTemplate", ""),
                        )
                    },
                },
            },
        )

        self.model.unit.status = ActiveStatus()

    def _rendered_webhook_definitions(self):
        ca_crt = b64encode(self._stored.ca.encode("ascii")).decode("utf-8")
        yaml_file = self.env.get_template("templates/webhooks.yaml.j2").render(ca_bundle=ca_crt)
        validating, mutating = yaml.safe_load_all(yaml_file)
        return validating, mutating

    def gen_certs(self):
        model = self.model.name
        app = self.model.app.name
        Path("/run/ssl.conf").write_text(
            f"""[ req ]
default_bits = 2048
prompt = no
default_md = sha256
req_extensions = req_ext
distinguished_name = dn
[ dn ]
C = GB
ST = Canonical
L = Canonical
O = Canonical
OU = Canonical
CN = 127.0.0.1
[ req_ext ]
subjectAltName = @alt_names
[ alt_names ]
DNS.1 = {app}
DNS.2 = {app}.{model}
DNS.3 = {app}.{model}.svc
DNS.4 = {app}.{model}.svc.cluster
DNS.5 = {app}.{model}.svc.cluster.local
IP.1 = 127.0.0.1
[ v3_ext ]
authorityKeyIdentifier=keyid,issuer:always
basicConstraints=CA:FALSE
keyUsage=keyEncipherment,dataEncipherment,digitalSignature
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=@alt_names"""
        )

        check_call(["openssl", "genrsa", "-out", "/run/ca.key", "2048"])
        check_call(["openssl", "genrsa", "-out", "/run/server.key", "2048"])
        check_call(
            [
                "openssl",
                "req",
                "-x509",
                "-new",
                "-sha256",
                "-nodes",
                "-days",
                "3650",
                "-key",
                "/run/ca.key",
                "-subj",
                "/CN=127.0.0.1",
                "-out",
                "/run/ca.crt",
            ]
        )
        check_call(
            [
                "openssl",
                "req",
                "-new",
                "-sha256",
                "-key",
                "/run/server.key",
                "-out",
                "/run/server.csr",
                "-config",
                "/run/ssl.conf",
            ]
        )
        check_call(
            [
                "openssl",
                "x509",
                "-req",
                "-sha256",
                "-in",
                "/run/server.csr",
                "-CA",
                "/run/ca.crt",
                "-CAkey",
                "/run/ca.key",
                "-CAcreateserial",
                "-out",
                "/run/cert.pem",
                "-days",
                "365",
                "-extensions",
                "v3_ext",
                "-extfile",
                "/run/ssl.conf",
            ]
        )

        return {
            "cert": Path("/run/cert.pem").read_text(),
            "key": Path("/run/server.key").read_text(),
            "ca": Path("/run/ca.crt").read_text(),
        }

    def _check_leader(self):
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise CheckFailed("Waiting for leadership", WaitingStatus)

    def _check_image_details(self):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            raise CheckFailed(f"{e.status.message}", e.status_type)
        return image_details


if __name__ == "__main__":
    main(Operator)
