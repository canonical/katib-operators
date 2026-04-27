# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

from charmed_kubeflow_chisme.components import Component
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from charmed_kubeflow_chisme.service_mesh import generate_allow_all_authorization_policy
from charms.istio_beacon_k8s.v0.service_mesh import (
    MeshType,
    PolicyResourceManager,
    ServiceMeshConsumer,
    UnitPolicy,
)
from lightkube import Client
from ops import ActiveStatus

logger = logging.getLogger(__name__)


class ServiceMeshComponent(Component):
    """Component to manage service mesh integration."""

    def __init__(
        self,
        *args,
        relation_name: str = "service-mesh",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self._relation_name = relation_name

        # Observe relation changed events
        self._events_to_observe = [
            self._charm.on[self._relation_name].relation_changed,
            self._charm.on[self._relation_name].relation_broken,
        ]

        # Initialize ServiceMeshConsumer to create the policy for metrics endpoint
        # The policy gets created when the service-mesh relation is established (with beacon)
        self._mesh = ServiceMeshConsumer(
            self._charm,
            policies=[
                UnitPolicy(
                    relation="metrics-endpoint",
                ),
            ],
        )

        self._policy_resource_manager = PolicyResourceManager(
            charm=self._charm,
            lightkube_client=Client(
                field_manager=f"{self._charm.app.name}-{self._charm.model.name}"
            ),
            labels={
                "app.kubernetes.io/instance": f"{self._charm.app.name}-{self._charm.model.name}",
                "kubernetes-resource-handler-scope": f"{self._charm.app.name}-allow-all",
            },
            logger=logger,
        )

        # Allow policy needed to allow the K8s API to talk to the webhook
        self._allow_all_policy = generate_allow_all_authorization_policy(
            app_name=self._charm.app.name,
            namespace=self._charm.model.name,
        )

    def _configure_app_leader(self, event):
        """Reconcile the allow-all policy when the app is leader."""
        policies = []

        # create the allow-all policy only when related to ambient
        if self._mesh._relation:
            logger.info("Integrated with ambient mesh, will create allow-all policy")
            policies.append(self._allow_all_policy)

        self._policy_resource_manager.reconcile(
            policies=[], mesh_type=MeshType.istio, raw_policies=policies
        )

    def remove(self, event):
        """Remove all policies on charm removal."""
        logger.info("Removing Authorization policies")
        self._policy_resource_manager.reconcile(
            policies=[], mesh_type=MeshType.istio, raw_policies=[]
        )

    def get_status(self):
        if self._mesh._relation:
            try:
                self._policy_resource_manager._validate_raw_policies([self._allow_all_policy])
            except (RuntimeError, TypeError) as e:
                raise GenericCharmRuntimeError(f"Error validating raw policies: {e}")
        return ActiveStatus()
