#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging

from ops.charm import CharmBase, RelationJoinedEvent
from ops.pebble import Layer, ChangeError
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube import Client
from lightkube.models.core_v1 import ServicePort


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
        self._name = self.model.app.name
        self._namespace = self.model.name
        self._container = self.unit.get_container(self._container_name)
        self._port = self.model.config["port"]
        port = ServicePort(int(self._port), name=f"{self.app.name}")
        self.service_patcher = KubernetesServicePatch(self, [port])
        self.lightkube_client = Client(
            namespace=self.model.name, field_manager="lightkube"
        )

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["ingress"].relation_changed,
            self.on.katib_ui_pebble_ready,
        ]:
            self.framework.observe(event, self.main)
        self.framework.observe(
            self.on.sidebar_relation_joined, self._on_sidebar_relation_joined
        )
        self.framework.observe(
            self.on.sidebar_relation_departed, self._on_sidebar_relation_departed
        )

    @property
    def container(self):
        return self._container

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

    def _update_layer(self) -> None:
        """Updates the Pebble configuration layer if changed."""
        current_layer = self.container.get_plan()
        new_layer = self._katib_ui_layer
        self.logger.debug(f"NEW LAYER: {new_layer}")
        if current_layer.services != new_layer.services:
            self.unit.status = MaintenanceStatus("Applying new pebble layer")
            self.container.add_layer(self._container_name, new_layer, combine=True)
            try:
                self.logger.info(
                    "Pebble plan updated with new configuration, replanning"
                )
                self.container.replan()
            except ChangeError:
                raise CheckFailed("Failed to replan", BlockedStatus)

    def _configure_ingress(self, interfaces):
        if interfaces["ingress"]:
            interfaces["ingress"].send_data(
                {
                    "prefix": "/katib/",
                    "service": self.model.app.name,
                    "port": self.model.config["port"],
                }
            )

    def _get_interfaces(self):
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(err, BlockedStatus)
        return interfaces

    # def _check_image_details(self):
    #     try:
    #         image_details = self.image.fetch()
    #     except OCIImageResourceError as e:
    #         raise CheckFailed(f"{e.status.message}", e.status_type)
    #     return image_details

    def _check_leader(self):
        if not self.unit.is_leader():
            raise CheckFailed("Waiting for leadership", WaitingStatus)

    def _check_container_connection(self):
        if not self.container.can_connect():
            raise CheckFailed("Pod startup is not complete", MaintenanceStatus)

    def _on_sidebar_relation_joined(self, event: RelationJoinedEvent):
        if not self.unit.is_leader():
            return
        event.relation.data[self.app].update(
            {
                "config": json.dumps(
                    [
                        {
                            "app": self.app.name,
                            "position": 5,
                            "type": "item",
                            "link": "/katib/",
                            "text": "Experiments (AutoML)",
                            "icon": "kubeflow:katib",
                        }
                    ]
                )
            }
        )

    def _on_sidebar_relation_departed(self, event):
        if not self.unit.is_leader():
            return
        event.relation.data[self.app].update({"config": json.dumps([])})

    def _handle_ingress(self, interfaces):
        if interfaces["ingress"]:
            interfaces["ingress"].send_data(
                {
                    "prefix": "/",
                    "rewrite": "/",
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
            self._update_layer()
        except CheckFailed as e:
            self.model.unit.status = e.status
            return
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(KatibUIOperator)
