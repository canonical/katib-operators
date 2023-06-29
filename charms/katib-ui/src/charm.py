#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler as KRH  # noqa: N817
from charmed_kubeflow_chisme.pebble import update_layer
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_sidebar import (
    KubeflowDashboardSidebarRequirer,
    SidebarItem,
)
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer
from serialized_data_interface import NoCompatibleVersions, NoVersionsListed, get_interfaces

K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2"]


class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


class KatibUIOperator(CharmBase):
    """Deploys the katib-ui service."""

    def __init__(self, framework):
        super().__init__(framework)
        self.logger = logging.getLogger(__name__)
        self._container_name = "katib-ui"
        self._namespace = self.model.name
        self._name = self.model.app.name
        self._container = self.unit.get_container(self._name)
        self._lightkube_field_manager = "lightkube"
        self._port = self.model.config["port"]
        port = ServicePort(int(self._port), name=f"{self.app.name}")
        self.service_patcher = KubernetesServicePatch(self, [port])
        self._k8s_resource_handler = None

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["ingress"].relation_changed,
            self.on.katib_ui_pebble_ready,
        ]:
            self.framework.observe(event, self.main)

        # add link to notebook in kubeflow-dashboard sidebar
        self.kubeflow_dashboard_sidebar = KubeflowDashboardSidebarRequirer(
            charm=self,
            relation_name="sidebar",
            sidebar_items=[
                SidebarItem(
                    text="Experiments (AutoML)", link="/katib/", type="item", icon="kubeflow:katib"
                )
            ],
        )

    @property
    def container(self):
        return self._container

    @property
    def k8s_resource_handler(self):
        if not self._k8s_resource_handler:
            self._k8s_resource_handler = KRH(
                field_manager=self._lightkube_field_manager,
                template_files=K8S_RESOURCE_FILES,
                context=self._context,
                logger=self.logger,
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._k8s_resource_handler

    @k8s_resource_handler.setter
    def k8s_resource_handler(self, handler: KRH):
        self._k8s_resource_handler = handler

    @property
    def _context(self):
        context = {"app_name": self.model.app.name, "namespace": self.model.name}
        return context

    @property
    def _katib_ui_layer(self) -> Layer:
        layer_config = {
            "summary": "katib-ui-operator layer",
            "description": "pebble config layer for katib-ui-operator",
            "services": {
                self._container_name: {
                    "override": "replace",
                    "summary": "entrypoint of the katib-ui-operator image",
                    "command": f"./katib-ui --port={self._port}",
                    "startup": "enabled",
                    "environment": {"KATIB_CORE_NAMESPACE": self.model.name},
                }
            },
        }
        return Layer(layer_config)

    def _deploy_k8s_resources(self) -> None:
        try:
            self.unit.status = MaintenanceStatus("Creating k8s resources")
            self.k8s_resource_handler.apply()
        except ApiError:
            raise CheckFailed("kubernetes resource creation failed", BlockedStatus)
        self.model.unit.status = ActiveStatus()

    def _get_interfaces(self):
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(err, BlockedStatus)
        return interfaces

    def _check_leader(self):
        if not self.unit.is_leader():
            raise CheckFailed("Waiting for leadership", WaitingStatus)

    def _check_container_connection(self):
        if not self.container.can_connect():
            raise CheckFailed("Pod startup is not complete", MaintenanceStatus)

    def _handle_ingress(self, interfaces):
        if interfaces["ingress"]:
            interfaces["ingress"].send_data(
                {
                    "prefix": "/katib/",
                    "rewrite": "/katib/",
                    "service": self.model.app.name,
                    "port": self.model.config["port"],
                }
            )

    def main(self, _) -> None:
        """Main entry point for the Charm."""
        try:
            self._check_container_connection()
            self._check_leader()
            interfaces = self._get_interfaces()
            self._handle_ingress(interfaces)
            self._deploy_k8s_resources()
            update_layer(self._container_name, self.container, self._katib_ui_layer, self.logger)
        except CheckFailed as e:
            self.model.unit.status = e.status
            return
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(KatibUIOperator)
