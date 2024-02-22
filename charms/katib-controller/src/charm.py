#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import tempfile
from base64 import b64encode
from pathlib import Path
from typing import Dict

import lightkube
import yaml
from charmed_kubeflow_chisme.components import ContainerFileTemplate
from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.kubernetes_component import KubernetesComponent
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from lightkube.models.core_v1 import ServicePort
from lightkube.resources.admissionregistration_v1 import (
    MutatingWebhookConfiguration,
    ValidatingWebhookConfiguration,
)
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.core_v1 import ConfigMap, ServiceAccount
from lightkube.resources.rbac_authorization_v1 import ClusterRole, ClusterRoleBinding
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main

from certs import gen_certs
from components.pebble_component import KatibControllerInputs, KatibControllerPebbleService

DEFAULT_IMAGES_FILE = "src/default-custom-images.json"
with open(DEFAULT_IMAGES_FILE, "r") as json_file:
    DEFAULT_IMAGES = json.load(json_file)

K8S_RESOURCE_FILES = [
    "src/templates/auth_manifests.yaml.j2",
    "src/templates/crds.yaml",
    "src/templates/webhooks.yaml.j2",
]
CONFIGMAP_FILES = [
    "src/templates/defaultTrialTemplate.yaml.j2",
    "src/templates/katib-config.yaml.j2",
]

CERTS_FOLDER = "/tmp/cert"
KATIB_CONFIG_FILE = Path("src/templates/katib-config.yaml.j2")
KATIB_CONFIG_DESTINTATION_PATH = "/katib-config/katib-config.yaml"

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
        raise err
    return images


class KatibControllerOperator(CharmBase):
    """Charm for the Katib controller component."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self._namespace = self.model.name

        # Expose controller's ports
        webhook_port = ServicePort(int(self.model.config["webhook-port"]), name="webhook")
        metrics_port = ServicePort(int(self.model.config["metrics-port"]), name="metrics")
        self.service_patcher = KubernetesServicePatch(
            self, [webhook_port, metrics_port], service_name=f"{self.model.app.name}"
        )

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

        # Charm logic
        self.charm_reconciler = CharmReconciler(self)

        # Generate self-signed certificates and store them
        self._gen_certs_if_missing()

        self.leadership_gate = self.charm_reconciler.add(
            component=LeadershipGateComponent(
                charm=self,
                name="leadership-gate",
            ),
            depends_on=[],
        )

        self.kubernetes_resources = self.charm_reconciler.add(
            component=KubernetesComponent(
                charm=self,
                name="kubernetes:auth-and-webhooks-and-crds",
                resource_templates=K8S_RESOURCE_FILES,
                krh_resource_types={
                    ClusterRole,
                    ClusterRoleBinding,
                    CustomResourceDefinition,
                    ServiceAccount,
                    MutatingWebhookConfiguration,
                    ValidatingWebhookConfiguration,
                },
                krh_labels=create_charm_default_labels(
                    self.app.name, self.model.name, scope="auth-and-webhooks-and-crds"
                ),
                context_callable=lambda: {
                    "app_name": self.app.name,
                    "namespace": self._namespace,
                    "ca_bundle": b64encode(self._stored.ca.encode("ascii")).decode("utf-8"),
                },
                lightkube_client=lightkube.Client(),
            ),
            depends_on=[self.leadership_gate],
        )

        self.configmap_resources = self.charm_reconciler.add(
            component=KubernetesComponent(
                charm=self,
                name="kubernetes:configmaps",
                resource_templates=CONFIGMAP_FILES,
                krh_resource_types={
                    ConfigMap,
                },
                krh_labels=create_charm_default_labels(
                    self.app.name, self.model.name, scope="configmaps"
                ),
                context_callable=lambda: dict(
                    {"webhookPort": self.model.config["webhook-port"]},
                    **self.get_images(
                        DEFAULT_IMAGES, parse_images_config(self.model.config["custom_images"])
                    ),
                ),
                lightkube_client=lightkube.Client(),
            ),
            depends_on=[self.leadership_gate],
        )

        # Create temporary files for the certificate data
        with tempfile.NamedTemporaryFile(delete=False) as key_file:
            key_file.write(self._stored.key.encode("utf-8"))

        with tempfile.NamedTemporaryFile(delete=False) as cert_file:
            cert_file.write(self._stored.cert.encode("utf-8"))

        with tempfile.NamedTemporaryFile(delete=False) as ca_file:
            ca_file.write(self._stored.ca.encode("utf-8"))

        self.custom_images = parse_images_config(self.model.config["custom_images"])
        self.images_context = self.get_images(DEFAULT_IMAGES, self.custom_images)

        self.katib_controller_container = self.charm_reconciler.add(
            component=KatibControllerPebbleService(
                charm=self,
                name="katib-controller-pebble-service",
                container_name="katib-controller",
                service_name="katib-controller",
                files_to_push=[
                    ContainerFileTemplate(
                        source_template_path=key_file.name,
                        destination_path=f"{CERTS_FOLDER}/tls.key",
                    ),
                    ContainerFileTemplate(
                        source_template_path=cert_file.name,
                        destination_path=f"{CERTS_FOLDER}/tls.crt",
                    ),
                    ContainerFileTemplate(
                        source_template_path=ca_file.name,
                        destination_path=f"{CERTS_FOLDER}/ca.crt",
                    ),
                    ContainerFileTemplate(
                        source_template_path=KATIB_CONFIG_FILE,
                        destination_path=KATIB_CONFIG_DESTINTATION_PATH,
                        context_function=lambda: dict(
                            {"webhookPort": self.model.config["webhook-port"]},
                            **self.get_images(
                                DEFAULT_IMAGES,
                                parse_images_config(self.model.config["custom_images"]),
                            ),
                        ),
                    ),
                ],
                inputs_getter=lambda: KatibControllerInputs(NAMESPACE=self.model.name),
            ),
            depends_on=[self.leadership_gate, self.kubernetes_resources, self.configmap_resources],
        )

        self.charm_reconciler.install_default_event_handlers()

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

    def _gen_certs_if_missing(self) -> None:
        """Generate certificates if they don't already exist in _stored."""
        logger.info("Generating certificates if missing.")
        cert_attributes = ["cert", "ca", "key"]
        # Generate new certs if any cert attribute is missing
        for cert_attribute in cert_attributes:
            try:
                getattr(self._stored, cert_attribute)
                logger.info(f"Certificate {cert_attribute} already exists, skipping generation.")
            except AttributeError:
                self._gen_certs()
                return

    def _gen_certs(self):
        """Refresh the certificates, overwriting all attributes if any attribute is missing."""
        logger.info("Generating certificates..")
        certs = gen_certs(
            model=self.model.name,
            app=self.model.app.name,
        )
        for k, v in certs.items():
            setattr(self._stored, k, v)


if __name__ == "__main__":
    main(KatibControllerOperator)
