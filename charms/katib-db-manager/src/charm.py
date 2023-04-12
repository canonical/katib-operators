#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer
from lightkube.models.core_v1 import ServicePort
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube.generic_resource import load_in_cluster_generic_resources
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from lightkube import ApiError
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charmed_kubeflow_chisme.pebble import update_layer


K8S_RESOURCE_FILES = [
    "src/templates/auth_manifests.yaml.j2",
]


class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


class KatibDBManagerOperator(CharmBase):
    """Deploys the katib-db-manager service."""

    def __init__(self, framework):
        super().__init__(framework)

        # retrieve configuration and base settings
        self.logger = logging.getLogger(__name__)
        self._container_name = "katib-db-manager"
        self._container = self.unit.get_container(self._container_name)
        self._exec_command = "./katib-db-manager"
        self._port = self.model.config["port"]
        self._lightkube_field_manager = "lightkube"
        self._namespace = self.model.name
        self._name = self.model.app.name
        self._k8s_resource_handler = None
        self._mysql_data = None

        # setup events to be handled by main event handler
        self.framework.observe(self.on["mysql"].relation_joined, self._on_event)
        self.framework.observe(self.on["mysql"].relation_changed, self._on_event)
        self.framework.observe(self.on.katib_db_manager_pebble_ready, self._on_event)
        self.framework.observe(self.on.config_changed, self._on_event)

        # setup events to be handled by specific event handlers
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.remove, self._on_remove)

        port = ServicePort(int(self._port), name="api")
        self.service_patcher = KubernetesServicePatch(
            self,
            [port],
            service_name=f"{self.model.app.name}",
        )

    @property
    def container(self):
        return self._container

    @property
    def _context(self):
        return {
            "app_name": self._name,
            "namespace": self._namespace,
        }

    @property
    def k8s_resource_handler(self):
        """Update K8S with K8S resources."""
        if not self._k8s_resource_handler:
            self._k8s_resource_handler = KubernetesResourceHandler(
                field_manager=self._lightkube_field_manager,
                template_files=K8S_RESOURCE_FILES,
                context=self._context,
                logger=self.logger,
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._k8s_resource_handler

    @k8s_resource_handler.setter
    def k8s_resource_handler(self, handler: KubernetesResourceHandler):
        self._k8s_resource_handler = handler

    @property
    def service_environment(self):
        """Return environment variables based on model configuration."""
        ret_env_vars = {
            "DB_NAME": "mysql",
            "DB_USER": "root",
            "DB_PASSWORD": self._mysql_data["root_password"],
            "KATIB_MYSQL_DB_HOST": self._mysql_data["host"],
            "KATIB_MYSQL_DB_PORT": self._mysql_data["port"],
            "KATIB_MYSQL_DB_DATABASE": self._mysql_data["database"],
        }

        return ret_env_vars

    @property
    def _katib_db_manager_layer(self) -> Layer:
        """Create and return Pebble framework layer."""
        layer_config = {
            "summary": "katib-db-manager layer",
            "description": "Pebble config layer for katib-db-manager operator",
            "services": {
                self._container_name: {
                    "override": "replace",
                    "summary": "Pebble service for katib-db-manager operator",
                    "startup": "enabled",
                    "command": self._exec_command,
                    "environment": self.service_environment,
                    "on-check-failure": {"katib-db-manager-up": "restart"},
                },
            },
            "checks": {
                "katib-db-manager-up": {
                    "override": "replace",
                    "period": "60s",
                    "timeout": "20s",
                    "threshold": 5,
                    "exec": {
                        "command": f"/bin/grpc_health_probe -addr=:{self._port}",
                    },
                }
            },
        }
        return Layer(layer_config)

    def _check_leader(self):
        """Check if this unit is a leader."""
        if not self.unit.is_leader():
            self.logger.info("Not a leader, skipping setup")
            raise ErrorWithStatus("Waiting for leadership", WaitingStatus)

    def _check_mysql(self):
        try:
            relation = self.model.relations["mysql"][0]
            unit = next(iter(relation.units))
            mysql_data = relation.data[unit]
            # Ensure we've got some data sent over the relation
            mysql_data["root_password"]
        except (IndexError, StopIteration, KeyError):
            raise ErrorWithStatus("Waiting for mysql connection information", WaitingStatus)

        return mysql_data

    def _check_and_report_k8s_conflict(self, error):
        """Return True if error status code is 409 (conflict), False otherwise."""
        if error.status.code == 409:
            self.logger.warning(f"Encountered a conflict: {error}")
            return True
        return False

    def _apply_k8s_resources(self, force_conflicts: bool = False) -> None:
        """Apply K8S resources.

        Args:
            force_conflicts (bool): *(optional)* Will "force" apply requests causing conflicting
                                    fields to change ownership to the field manager used in this
                                    charm.
                                    NOTE: This will only be used if initial regular apply() fails.
        """
        self.unit.status = MaintenanceStatus("Creating K8S resources")
        try:
            self.k8s_resource_handler.apply()
        except ApiError as error:
            if self._check_and_report_k8s_conflict(error) and force_conflicts:
                # conflict detected when applying K8S resources
                # re-apply K8S resources with forced conflict resolution
                self.unit.status = MaintenanceStatus("Force applying K8S resources")
                self.logger.warning("Apply K8S resources with forced changes against conflicts")
                self.k8s_resource_handler.apply(force=force_conflicts)
            else:
                raise GenericCharmRuntimeError("K8S resources creation failed") from error
        self.model.unit.status = MaintenanceStatus("K8S resources created")

    def _on_install(self, _):
        """Installation only tasks."""
        # deploy K8S resources to speed up deployment
        self._apply_k8s_resources()

    def _on_remove(self, _):
        """Remove all resources."""
        self.unit.status = MaintenanceStatus("Removing K8S resources")
        k8s_resources_manifests = self.k8s_resource_handler.render_manifests()
        try:
            delete_many(self.k8s_resource_handler.lightkube_client, k8s_resources_manifests)
        except ApiError as error:
            # do not log/report when resources were not found
            if error.status.code != 404:
                self.logger.error(f"Failed to delete CRD resources, with error: {error}")
                raise error

        self.unit.status = MaintenanceStatus("K8S resources removed")

    def _on_event(self, event, force_conflicts: bool = False) -> None:
        """Perform all required actions for the Charm.

        Args:
            force_conflicts (bool): Should only be used when need to resolved conflicts on K8S
                                    resources.
        """
        try:
            self._check_leader()
            self._apply_k8s_resources(force_conflicts=force_conflicts)
            self._mysql_data = self._check_mysql()
            update_layer(
                self._container_name,
                self._container,
                self._katib_db_manager_layer,
                self.logger,
            )
        except ErrorWithStatus as err:
            self.model.unit.status = err.status
            self.logger.error(f"Failed to handle {event} with error: {err}")
            return

        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(KatibDBManagerOperator)
