#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charmed_kubeflow_chisme.pebble import update_layer
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
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
MYSQL_WARNING = "Relation mysql is deprecated."
UNBLOCK_MESSAGE = "Remove deprecated mysql relation to unblock."


class KatibDBManagerOperator(CharmBase):
    """Deploys the katib-db-manager service."""

    def __init__(self, framework):
        super().__init__(framework)

        # retrieve configuration and base settings
        self.logger = logging.getLogger(__name__)
        self._container_name = "katib-db-manager"
        self._database_name = "mysql"
        self._container = self.unit.get_container(self._container_name)
        self._exec_command = "./katib-db-manager"
        self._port = self.model.config["port"]
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
        self.framework.observe(self.on["mysql"].relation_joined, self._on_mysql_relation)
        self.framework.observe(self.on["mysql"].relation_changed, self._on_mysql_relation)
        self.framework.observe(self.on["mysql"].relation_departed, self._on_mysql_relation_remove)
        self.framework.observe(self.on["mysql"].relation_broken, self._on_mysql_relation_remove)
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
            "DB_NAME": self._db_data["db_name"],
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

    def _on_mysql_relation(self, event):
        """Check for existing database relations and process mysql relation if needed."""
        # check for relational-db relation
        # relying on KeyError to ensure that relational-db relation is not present
        try:
            relation = self.model.get_relation("relational-db")
            if relation:
                self.logger.warning(
                    "Up-to-date database relation relational-db is already established."
                )
                self.logger.error(f"{MYSQL_WARNING} {UNBLOCK_MESSAGE}")
                self.model.unit.status = BlockedStatus(f"{UNBLOCK_MESSAGE} See logs")
                return
        except KeyError:
            pass
        # relational-db relation was not found, proceed with warnings
        self.logger.warning(MYSQL_WARNING)
        self.model.unit.status = MaintenanceStatus(f"Adding mysql relation. {MYSQL_WARNING}")
        self._on_event(event)

    def _on_mysql_relation_remove(self, event):
        """Process removal of mysql relation."""
        self.model.unit.status = MaintenanceStatus(f"Removing mysql relation. {MYSQL_WARNING}")
        self._on_event(event)

    def _on_relational_db_relation(self, event):
        """Check for existing database relations and process relational-db relation if needed."""
        # relying on KeyError to ensure that mysql relation is not present
        try:
            relation = self.model.get_relation("mysql")
            if relation:
                self.logger.warning(
                    "Failed to create relational-db relation due to existing mysql relation."
                )
                self.logger.error(f"{MYSQL_WARNING} {UNBLOCK_MESSAGE}")
                self.model.unit.status = BlockedStatus(f"{UNBLOCK_MESSAGE} See logs")
                return
        except KeyError:
            pass
        # mysql relation was not found, proceed
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

    def _get_mysql_data(self) -> dict:
        """Check mysql relation, retrieve and return data, if available."""
        db_data = {}
        relation_data = {}
        relation = self._get_db_relation("mysql")

        # retrieve database data from relation
        try:
            unit = next(iter(relation.units))
            relation_data = relation.data[unit]
            # retrieve database data from relation data
            # this also validates the expected data by means of KeyError exception
            db_data["db_name"] = self._database_name
            db_data["db_username"] = relation_data["user"]
            db_data["db_password"] = relation_data["root_password"]
            db_data["katib_db_host"] = relation_data["host"]
            db_data["katib_db_port"] = relation_data["port"]
            db_data["katib_db_name"] = relation_data["database"]
        except (IndexError, StopIteration, KeyError) as err:
            # failed to retrieve database configuration
            if not relation_data:
                raise GenericCharmRuntimeError(
                    "Database relation mysql is not established or empty"
                )
            self.logger.error(f"Missing attribute {err} in mysql relation data")
            # incorrect/incomplete data can be found in mysql relation which can be resolved:
            # use WaitingStatus
            raise ErrorWithStatus(
                "Incorrect/incomplete data found in relation mysql. See logs", WaitingStatus
            )

        return db_data

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
                db_data["db_name"] = self._database_name
                db_data["db_username"] = val["username"]
                db_data["db_password"] = val["password"]
                host, port = val["endpoints"].split(":")
                db_data["katib_db_host"] = host
                db_data["katib_db_port"] = port
                db_data["katib_db_name"] = "database"
            except KeyError as err:
                self.logger.error(f"Missing attribute {err} in relational-db relation data")
                # incorrect/incomplete data can be found in mysql relation which can be
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
        """Check for MySQL relations -  mysql or relational-db - and retrieve data.

        Only one database relation can be established at a time.
        """
        db_data = {}
        try:
            db_data = self._get_mysql_data()
        except ErrorWithStatus as err:
            # mysql relation is established, but data could not be retrieved
            raise err
        except GenericCharmRuntimeError:
            # mysql relation is not established, proceed to check for relational-db relation
            try:
                db_data = self._get_relational_db_data()
            except ErrorWithStatus as err:
                # relation-db relation is established, but data could not be retrieved
                raise err
            except GenericCharmRuntimeError:
                # mysql and relational-db relations are not established, raise error
                raise ErrorWithStatus(
                    "Please add required database relation: eg. relational-db", BlockedStatus
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
        # skip update status processing in case of BlockedStatus
        if isinstance(self.model.unit.status, BlockedStatus):
            return
        try:
            self._refresh_status()
        except ErrorWithStatus as err:
            self.model.unit.status = err.status

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
