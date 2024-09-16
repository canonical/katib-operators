#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charmed_kubeflow_chisme.pebble import update_layer
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.mlops_libs.v0.k8s_service_info import KubernetesServiceInfoProvider
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, ModelError, WaitingStatus
from ops.pebble import CheckStatus, Layer

K8S_RESOURCE_FILES = [
    "src/templates/auth_manifests.yaml.j2",
]
# Value is hardcoded in upstream
# https://github.com/kubeflow/katib/blob/7959ffd54851216dbffba791e1da13c8485d1085/cmd/db-manager/v1beta1/main.go#L38
SERVICE_PORT = 6789


class KatibDBManagerOperator(CharmBase):
    """Deploys the katib-db-manager service."""

    def __init__(self, framework):
        super().__init__(framework)

        # retrieve configuration and base settings
        self.logger = logging.getLogger(__name__)
        self._container_name = "katib-db-manager"
        self._database_name = "katib"
        self._container = self.unit.get_container(self._container_name)
        self._exec_command = "./katib-db-manager"
        self._lightkube_field_manager = "lightkube"
        self._namespace = self.model.name
        self._name = self.model.app.name
        self._k8s_resource_handler = None
        self._db_data = None

        # setup events to be handled by main event handler
        self.framework.observe(self.on.katib_db_manager_pebble_ready, self._on_event)
        self.framework.observe(self.on.config_changed, self._on_event)

        # setup events to be handled by specific event handlers
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(
            self.on["relational-db"].relation_joined, self._on_relational_db_relation
        )
        self.framework.observe(
            self.on["relational-db"].relation_changed, self._on_relational_db_relation
        )
        self.framework.observe(
            self.on["relational-db"].relation_departed, self._on_relational_db_relation_remove
        )
        self.framework.observe(
            self.on["relational-db"].relation_broken, self._on_relational_db_relation_remove
        )

        # setup relational database interface and observers
        self.database = DatabaseRequires(
            self, relation_name="relational-db", database_name=self._database_name
        )
        self.framework.observe(self.database.on.database_created, self._on_relational_db_relation)
        self.framework.observe(self.database.on.endpoints_changed, self._on_relational_db_relation)

        port = ServicePort(int(SERVICE_PORT), name="api")
        self.service_patcher = KubernetesServicePatch(
            self,
            [port],
            service_name=f"{self.model.app.name}",
        )

        # KubernetesServiceInfoProvider for broadcasting the service information
        self._k8s_svc_info_provider = KubernetesServiceInfoProvider(
            charm=self,
            name=self._container_name,
            port=str(SERVICE_PORT),
            refresh_event=self.on.config_changed,
        )

        self._logging = LogForwarder(charm=self)

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
            "DB_NAME": self._db_data["db_type"],
            "DB_USER": self._db_data["db_username"],
            "DB_PASSWORD": self._db_data["db_password"],
            "KATIB_MYSQL_DB_HOST": self._db_data["katib_db_host"],
            "KATIB_MYSQL_DB_PORT": self._db_data["katib_db_port"],
            "KATIB_MYSQL_DB_DATABASE": self._db_data["katib_db_name"],
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
                    "override": "merge",
                    "summary": "Pebble service for katib-db-manager operator",
                    "startup": "enabled",
                    "command": self._exec_command,
                    "environment": self.service_environment,
                    # Disable health checks due to issue #128.
                    # FIXME: uncomment when https://github.com/canonical/katib-operators/issues/128 is closed.  # noqa E501
                    # "on-check-failure": {"katib-db-manager-up": "restart"},
                },
            },
            # Disable health checks due to issue #128.
            # FIXME: uncomment when https://github.com/canonical/katib-operators/issues/128 is closed.  # noqa E501
            # "checks": {
            #     "katib-db-manager-up": {
            #         "override": "replace",
            #         "period": "60s",
            #         "timeout": "20s",
            #         "threshold": 5,
            #         "exec": {
            #             "command": f"/bin/grpc_health_probe -addr=:{self._port}",
            #         },
            #     }
            # },
        }
        return Layer(layer_config)

    def _check_leader(self):
        """Check if this unit is a leader."""
        if not self.unit.is_leader():
            self.logger.info("Not a leader, skipping setup")
            raise ErrorWithStatus("Waiting for leadership", WaitingStatus)

    def _on_relational_db_relation(self, event):
        """Process relational-db relation."""
        self.model.unit.status = MaintenanceStatus("Adding relational-db relation")
        self._on_event(event)

    def _on_relational_db_relation_remove(self, event):
        """Process removal of relational-db relation."""
        self.model.unit.status = MaintenanceStatus("Removing relational-db relation")
        self._on_event(event)

    def _get_db_relation(self, relation_name):
        """Retrieves relation with supplied relation name, if it is established.

        Returns relation, if it is established, and raises error otherwise."""

        try:
            # retrieve relation data
            relation = self.model.get_relation(relation_name)
        except KeyError:
            # relation was not found
            relation = None
        if not relation:
            # relation is not established, raise an error
            raise GenericCharmRuntimeError(
                f"Database relation {relation_name} is not established or empty"
            )

        return relation

    def _get_relational_db_data(self) -> dict:
        """Check relational-db relation, retrieve and return data, if available."""
        db_data = {}
        relation_data = {}

        # ignore return value, because data is retrieved from library
        self._get_db_relation("relational-db")

        # retrieve database data from library
        relation_data = self.database.fetch_relation_data()
        # parse data in relation
        # this also validates expected data by means of KeyError exception
        for val in relation_data.values():
            if not val:
                continue
            try:
                db_data["db_type"] = "mysql"
                db_data["db_username"] = val["username"]
                db_data["db_password"] = val["password"]
                host, port = val["endpoints"].split(":")
                db_data["katib_db_host"] = host
                db_data["katib_db_port"] = port
                db_data["katib_db_name"] = self._database_name
            except KeyError as err:
                self.logger.error(f"Missing attribute {err} in relational-db relation data")
                # incorrect/incomplete data can be found in relational-db relation which can be
                # resolved: use WaitingStatus
                raise ErrorWithStatus(
                    "Incorrect/incomplete data found in relation relational-db. See logs",
                    WaitingStatus,
                )
        # report if there was no data populated
        if not db_data:
            self.logger.info("Found empty relation data for relational-db relation.")
            raise ErrorWithStatus("Waiting for relational-db data", WaitingStatus)

        return db_data

    def _get_db_data(self) -> dict:
        """Check for MySQL relational-db relation and retrieve data."""
        db_data = {}
        try:
            db_data = self._get_relational_db_data()
        except ErrorWithStatus as err:
            # relation-db relation is established, but data could not be retrieved
            raise err
        except GenericCharmRuntimeError:
            # relational-db relation is not established, raise error
            raise ErrorWithStatus(
                "Please add required database relation: relational-db", BlockedStatus
            )

        return db_data

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

    def _get_check_status(self):
        return self.container.get_check("katib-db-manager-up").status

    def _refresh_status(self):
        """Check leader, refresh status of workload, and raise error if workload is unhealthy."""
        self._check_leader()
        try:
            check = self._get_check_status()
        except ModelError as error:
            raise GenericCharmRuntimeError(
                "Failed to run health check on workload container"
            ) from error
        if check != CheckStatus.UP:
            self.logger.error(
                f"Container {self._container_name} failed health check. It will be restarted."
            )
            raise ErrorWithStatus("Workload failed health check", MaintenanceStatus)

    def _on_update_status(self, event):
        """Update status actions."""
        self._on_event(event)
        # Disable health checks due to issue #128.
        # FIXME: uncomment when https://github.com/canonical/katib-operators/issues/128 is closed.
        # try:
        #     self._refresh_status()
        # except ErrorWithStatus as err:
        #     self.model.unit.status = err.status

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
            self._db_data = self._get_db_data()
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
