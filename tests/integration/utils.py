import tenacity
import yaml
from lightkube.generic_resource import create_namespaced_resource

EXPERIMENT = create_namespaced_resource(
    group="kubeflow.org",
    version="v1beta1",
    kind="experiment",
    plural="experiments",
    verbs=None,
)


def create_experiment(client, exp_path, namespace) -> str:
    """Create Experiment instance."""
    with open(exp_path) as f:
        exp_yaml = yaml.safe_load(f.read())
    exp_object = EXPERIMENT(exp_yaml)
    client.create(exp_object, namespace=namespace)
    return exp_yaml["metadata"]["name"]


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
    stop=tenacity.stop_after_attempt(10),
    reraise=True,
)
def assert_exp_status_running(logger, client, name, namespace):
    """Asserts the experiment status is Running.
    Retries multiple times using tenacity to allow time for the experiment
    to change its status from None -> Created -> Running
    """
    exp_status = client.get(EXPERIMENT.Status, name=name, namespace=namespace).status[
        "conditions"
    ][-1]["type"]

    logger.info(f"Experiment Status is {exp_status}")

    # Check experiment is running
    assert exp_status == "Running", f"{name} not running status = {exp_status})"


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, min=1, max=15),
    stop=tenacity.stop_after_attempt(10),
    reraise=True,
)
def assert_trial_status_running(logger, client, resource_class, experiment_name, namespace):
    """Asserts the trial status is Running.
    Retries multiple times using tenacity to allow the trial
    to be in Running state
    """
    trials = client.list(
        resource_class,
        namespace=namespace,
        labels={"katib.kubeflow.org/experiment": experiment_name},
    )
    trial = next(trials)
    trial_status = trial.status["conditions"][-1]["type"]
    logger.info(f"Trial Status is {trial_status}")
    assert trial_status == "Running", f"{trial.metadata.name} not running, status = {trial_status}"
