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
def assert_experiment_exists(client, name, namespace):
    """Asserts on the presence of the experiment in the cluster.

    Retries multiple times using tenacity to allow time for the experiment
    to be created.
    """
    try:
        client.get(EXPERIMENT, name=name, namespace=namespace)
    except ApiError:
        raise AssertionError(
            f"Waited too long to get experiment. \
            Experiment {name} in namespace {namespace} does not exist when it should."
        )


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(80),
    reraise=True,
)
def assert_experiment_status_running_succeeded(logger, client, name, namespace):
    """Asserts the experiment status is Running or Succeeded.

    Retries multiple times using tenacity to allow time for the experiment
    to change its status from None -> Created -> Running/Succeeded.
    """
    try:
        experiment_status = client.get(EXPERIMENT.Status, name=name, namespace=namespace).status[
            "conditions"
        ][-1]["type"]
    except Exception as e:  # TODO: make the exception more specific
        raise AssertionError(
            f"Unable to get the status of Experiment {name} in Namespace {namespace}. Error: {e}"
        )

    logger.info(f"Experiment Status is {experiment_status}")

    # Check experiment is running or succeeded
    assert experiment_status in [
        "Running",
        "Succeeded",
    ], f"Experiment {name} not in Running/Succeeded (status = {experiment_status})"


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, min=1, max=10),
    stop=tenacity.stop_after_attempt(10),
    reraise=True,
)
def assert_experiment_deleted(logger, client, experiment_name, namespace):
    """Assert that the Katib experiment is deleted.

    Retries multiple times to allow for the experiment to be deleted.
    """
    logger.info(f"Waiting for Experiment/{experiment_name} to be deleted.")
    deleted = False
    try:
        client.get(EXPERIMENT, experiment_name, namespace=namespace)
    except ApiError as error:
        logger.info(f"Not found Experiment/{experiment_name}. Status {error.status.code} ")
        if error.status.code == 404:
            deleted = True

    assert deleted, f"Waited too long for Experiment/{experiment_name} to be deleted!"
