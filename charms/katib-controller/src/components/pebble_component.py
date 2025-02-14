# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
import logging

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class KatibControllerInputs:
    """Defines the required inputs for KatibControllerPebbleService."""

    NAMESPACE: str
    KATIB_DB_MANAGER_SERVICE_PORT: str


class KatibControllerPebbleService(PebbleServiceComponent):
    def get_layer(self) -> Layer:
        """Defines and returns Pebble layer configuration

        This method is required for subclassing PebbleServiceContainer
        """
        logger.info("PebbleServiceComponent.get_layer executing")

        try:
            inputs: KatibControllerInputs = self._inputs_getter()
        except Exception as err:
            raise ValueError("Failed to get inputs for Pebble container.") from err

        return Layer(
            {
                "summary": "katib-controller layer",
                "description": "Pebble config layer for katib-controller",
                "services": {
                    self.service_name: {
                        "override": "replace",
                        "summary": "Entry point for katib-controller image",
                        "command": "./katib-controller --katib-config=/katib-config/katib-config.yaml",  # noqa E501
                        "startup": "enabled",
                        "environment": {
                            "KATIB_CORE_NAMESPACE": str(inputs.NAMESPACE).lower(),
                            "KATIB_DB_MANAGER_SERVICE_PORT": str(
                                inputs.KATIB_DB_MANAGER_SERVICE_PORT
                            ),
                        },
                    }
                },
            }
        )
