# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import tenacity
import yaml
from lightkube import ApiError
from lightkube.generic_resource import create_namespaced_resource

EXPERIMENT = create_namespaced_resource(
    group="kubeflow.org",
    version="v1beta1",
    kind="experiment",
    plural="experiments",
    verbs=None,
)

TRIAL = create_namespaced_resource(
    group="kubeflow.org",
    version="v1beta1",
    kind="trial",
    plural="trials",
    verbs=None,
)


def create_experiment(client, exp_path, namespace) -> str:
    """Create Experiment instance."""
    with open(exp_path) as f:
        exp_yaml = yaml.safe_load(f.read())
    exp_object = EXPERIMENT(exp_yaml)
    client.create(exp_object, namespace=namespace)
    return exp_yaml["metadata"]["name"]


def delete_experiment(client, name, namespace):
    """Delete Experiment instance."""
    client.delete(EXPERIMENT, name=name, namespace=namespace)


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=15),
    stop=tenacity.stop_after_delay(30),
    reraise=True,
)
def assert_get_experiment(logger, client, name, namespace):
    """Asserts on the presence of the experiment in the cluster.
    Retries multiple times using tenacity to allow time for the experiment
    to be created.
    """
    exp = client.get(EXPERIMENT, name=name, namespace=namespace)

    assert exp is not None, f"{name} does not exist"


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(80),
    reraise=True,
)
def assert_exp_status_succeeded(logger, client, name, namespace):
    """Asserts the experiment status is Succeeded.
    Retries multiple times using tenacity to allow time for the experiment
    to change its status from None -> Created -> Running -> Succeeded.
    """
    exp_status = client.get(EXPERIMENT.Status, name=name, namespace=namespace).status[
        "conditions"
    ][-1]["type"]

    logger.info(f"Experiment Status is {exp_status}")

    # Check experiment is succeeded
    assert exp_status == "Succeeded", f"{name} not Succeeded status = {exp_status})"


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, min=1, max=10),
    stop=tenacity.stop_after_attempt(10),
    reraise=True,
)
def assert_deleted(logger, client, experiment_name, namespace):
    """Test for deleted resource. Retries multiple times to allow experiment to be deleted."""
    logger.info(f"Waiting for {EXPERIMENT}/{experiment_name} to be deleted.")
    deleted = False
    try:
        client.get(EXPERIMENT, experiment_name, namespace=namespace)
    except ApiError as error:
        logger.info(f"Not found {EXPERIMENT}/{experiment_name}. Status {error.status.code} ")
        if error.status.code == 404:
            deleted = True

    assert deleted, f"Waited too long for {EXPERIMENT}/{experiment_name} to be deleted!"
