import json
import os
from pathlib import Path
from pickle import DEFAULT_PROTOCOL, PicklingError
from typing import Any, Dict, Optional

from packaging import version

from huggingface_hub import snapshot_download
from huggingface_hub.constants import CONFIG_NAME
from huggingface_hub.file_download import (
    _PY_VERSION,
    get_fastai_version,
    get_fastcore_version,
)
from huggingface_hub.hf_api import HfApi, HfFolder
from huggingface_hub.repository import Repository
from huggingface_hub.utils import logging


logger = logging.get_logger(__name__)


def _check_fastai_fastcore_versions(
    fastai_min_version: Optional[str] = "2.4",
    fastcore_min_version: Optional[str] = "1.3.27",
):
    """
    Checks that the installed fastai and fastcore versions are compatible for pickle serialization.

    Args:
        fastai_min_version (`str`, *optional*):
            The minimum fastai version supported.
        fastcore_min_version (`str`, *optional*):
            The minimum fastcore version supported.

    <Tip>
    Raises the following error:

        - [`ImportError`](https://docs.python.org/3/library/exceptions.html#ImportError)
          if the fastai or fastcore libraries are not available or are of an invalid version.

    </Tip>
    """

    if (get_fastcore_version() or get_fastai_version()) == "N/A":
        raise ImportError(
            f"fastai>={fastai_min_version} and fastcore>={fastcore_min_version} are"
            f" required. Currently using fastai=={get_fastai_version()} and"
            f" fastcore=={get_fastcore_version()}."
        )

    current_fastai_version = version.Version(get_fastai_version())
    current_fastcore_version = version.Version(get_fastcore_version())

    if current_fastai_version < version.Version(fastai_min_version):
        raise ImportError(
            "`push_to_hub_fastai` and `from_pretrained_fastai` require a"
            f" fastai>={fastai_min_version} version, but you are using fastai version"
            f" {get_fastai_version()} which is incompatible. Upgrade with `pip install"
            " fastai==2.5.6`."
        )

    if current_fastcore_version < version.Version(fastcore_min_version):
        raise ImportError(
            "`push_to_hub_fastai` and `from_pretrained_fastai` require a"
            f" fastcore>={fastcore_min_version} version, but you are using fastcore"
            f" version {get_fastcore_version()} which is incompatible. Upgrade with"
            " `pip install fastcore==1.3.27`."
        )


def _check_fastai_fastcore_pyproject_versions(
    storage_folder: str,
    fastai_min_version: Optional[str] = "2.4",
    fastcore_min_version: Optional[str] = "1.3.27",
):
    """
    Checks that the `pyproject.toml` file in the directory `storage_folder` has fastai and fastcore versions
    that are compatible with `from_pretrained_fastai` and `push_to_hub_fastai`. If `pyproject.toml` does not exist
    or does not contain versions for fastai and fastcore, then it logs a warning.

    Args:
        storage_folder (`str`):
            Folder to look for the `pyproject.toml` file.
        fastai_min_version (`str`, *optional*):
            The minimum fastai version supported.
        fastcore_min_version (`str`, *optional*):
            The minimum fastcore version supported.

    <Tip>
    Raises the following errors:

        - [`ImportError`](https://docs.python.org/3/library/exceptions.html#ImportError)
          if the `toml` module is not installed.
        - [`ImportError`](https://docs.python.org/3/library/exceptions.html#ImportError)
          if the `pyproject.toml` indicates a lower than minimum supported version of fastai or fastcore.

    </Tip>
    """

    try:
        import toml
    except ModuleNotFoundError:
        raise ImportError(
            "`push_to_hub_fastai` and `from_pretrained_fastai` require the toml module."
            " Install it with `pip install toml`."
        )

    # Checks that a `pyproject.toml`, with `build-system` and `requires` sections, exists in the repository. If so, get a list of required packages.
    if not os.path.isfile(f"{storage_folder}/pyproject.toml"):
        logger.warning(
            "There is no `pyproject.toml` in the repository that contains the fastai"
            " `Learner`. The `pyproject.toml` would allow us to verify that your fastai"
            " and fastcore versions are compatible with those of the model you want to"
            " load."
        )
        return
    pyproject_toml = toml.load(f"{storage_folder}/pyproject.toml")

    if "build-system" not in pyproject_toml.keys():
        logger.warning(
            "There is no `build-system` section in the pyproject.toml of the repository"
            " that contains the fastai `Learner`. The `build-system` would allow us to"
            " verify that your fastai and fastcore versions are compatible with those"
            " of the model you want to load."
        )
        return
    build_system_toml = pyproject_toml["build-system"]

    if "requires" not in build_system_toml.keys():
        logger.warning(
            "There is no `requires` section in the pyproject.toml of the repository"
            " that contains the fastai `Learner`. The `requires` would allow us to"
            " verify that your fastai and fastcore versions are compatible with those"
            " of the model you want to load."
        )
        return
    package_versions = build_system_toml["requires"]

    # Extracts contains fastai and fastcore versions from `pyproject.toml` if available.
    # If the package is specified but not the version (e.g. "fastai" instead of "fastai=2.4"), the default versions are the highest.
    fastai_packages = [pck for pck in package_versions if pck.startswith("fastai")]
    if len(fastai_packages) == 0:
        logger.warning(
            "The repository does not have a fastai version specified in the"
            " `pyproject.toml`."
        )
    # fastai_version is an empty string if not specified
    else:
        fastai_version = str(fastai_packages[0]).partition("=")[2]
        if fastai_version != "" and version.Version(fastai_version) < version.Version(
            fastai_min_version
        ):
            raise ImportError(
                "`from_pretrained_fastai` requires"
                f" fastai>={fastai_min_version} version but the model to load uses"
                f" {fastai_version} which is incompatible."
            )

    fastcore_packages = [pck for pck in package_versions if pck.startswith("fastcore")]
    if len(fastcore_packages) == 0:
        logger.warning(
            "The repository does not have a fastcore version specified in the"
            " `pyproject.toml`."
        )
    # fastcore_version is an empty string if not specified
    else:
        fastcore_version = str(fastcore_packages[0]).partition("=")[2]
        if fastcore_version != "" and version.Version(
            fastcore_version
        ) < version.Version(fastcore_min_version):
            raise ImportError(
                "`from_pretrained_fastai` requires"
                f" fastcore>={fastcore_min_version} version, but you are using fastcore"
                f" version {fastcore_version} which is incompatible."
            )


README_TEMPLATE = """---
tags:
- fastai
---

# Amazing!

🥳 Congratulations on hosting your fastai model on the Hugging Face Hub!

# Some next steps
1. Fill out this model card with more information (see the template below and the [documentation here](https://huggingface.co/docs/hub/model-repos))!

2. Create a demo in Gradio or Streamlit using 🤗 Spaces ([documentation here](https://huggingface.co/docs/hub/spaces)).

3. Join the fastai community on the [Fastai Discord](https://discord.com/invite/YKrxeNn)!

Greetings fellow fastlearner 🤝! Don't forget to delete this content from your model card.


---


# Model card

## Model description
More information needed

## Intended uses & limitations
More information needed

## Training and evaluation data
More information needed
"""

PYPROJECT_TEMPLATE = f"""[build-system]
requires = ["setuptools>=40.8.0", "wheel", "python={_PY_VERSION}", "fastai={get_fastai_version()}", "fastcore={get_fastcore_version()}"]
build-backend = "setuptools.build_meta:__legacy__"
"""


def _create_model_card(repo_dir: Path):
    """
    Creates a model card for the repository.

    Args:
        repo_dir (`Path`):
            Directory where model card is created.
    """
    readme_path = repo_dir / "README.md"

    if not readme_path.exists():
        with readme_path.open("w", encoding="utf-8") as f:
            f.write(README_TEMPLATE)


def _create_model_pyproject(repo_dir: Path):
    """
    Creates a `pyproject.toml` for the repository.

    Args:
        repo_dir (`Path`):
            Directory where `pyproject.toml` is created.
    """
    pyproject_path = repo_dir / "pyproject.toml"

    if not pyproject_path.exists():
        with pyproject_path.open("w", encoding="utf-8") as f:
            f.write(PYPROJECT_TEMPLATE)


def _save_pretrained_fastai(
    learner,
    save_directory: str,
    config: Optional[Dict[str, Any]] = None,
):
    """
    Saves a fastai learner to `save_directory` in pickle format using the default pickle protocol for the version of python used.

    Args:
        learner (`Learner`):
            The `fastai.Learner` you'd like to save.
        save_directory (`str`):
            Specific directory in which you want to save the fastai learner.
        config (`dict`, *optional*):
            Configuration object. Will be uploaded as a .json file. Example: 'https://huggingface.co/espejelomar/fastai-pet-breeds-classification/blob/main/config.json'.

    <Tip>

    Raises the following error:

        - [`RuntimeError`](https://docs.python.org/3/library/exceptions.html#RuntimeError)
          if the config file provided is not a dictionary.

    </Tip>
    """
    _check_fastai_fastcore_versions()

    os.makedirs(save_directory, exist_ok=True)

    # if the user provides config then we update it with the fastai and fastcore versions in CONFIG_TEMPLATE.
    if config is not None:
        if not isinstance(config, dict):
            raise RuntimeError(
                f"Provided config should be a dict. Got: '{type(config)}'"
            )
        path = os.path.join(save_directory, CONFIG_NAME)
        with open(path, "w") as f:
            json.dump(config, f)

    _create_model_card(Path(save_directory))
    _create_model_pyproject(Path(save_directory))

    # learner.export saves the model in `self.path`.
    learner.path = Path(save_directory)
    os.makedirs(save_directory, exist_ok=True)
    try:
        learner.export(
            fname="model.pkl",
            pickle_protocol=DEFAULT_PROTOCOL,
        )
    except PicklingError:
        raise PicklingError(
            "You are using a lambda function, i.e., an anonymous function. `pickle`"
            " cannot pickle function objects and requires that all functions have"
            " names. One possible solution is to name the function."
        )


def from_pretrained_fastai(
    repo_id: str,
    revision: Optional[str] = None,
):
    """
    Load pretrained fastai model from the Hub or from a local directory.

    Args:
        repo_id (`str`):
            The location where the pickled fastai.Learner is. It can be either of the two:
                - Hosted on the Hugging Face Hub. E.g.: 'espejelomar/fatai-pet-breeds-classification' or 'distilgpt2'.
                  You can add a `revision` by appending `@` at the end of `repo_id`. E.g.: `dbmdz/bert-base-german-cased@main`.
                  Revision is the specific model version to use. Since we use a git-based system for storing models and other
                  artifacts on the Hugging Face Hub, it can be a branch name, a tag name, or a commit id.
                - Hosted locally. `repo_id` would be a directory containing the pickle and a pyproject.toml
                  indicating the fastai and fastcore versions used to build the `fastai.Learner`. E.g.: `./my_model_directory/`.
        revision (`str`, *optional*):
            Revision at which the repo's files are downloaded. See documentation of `snapshot_download`.

    Returns:
        The `fastai.Learner` model in the `repo_id` repo.
    """
    _check_fastai_fastcore_versions()

    # Load the `repo_id` repo.
    # `snapshot_download` returns the folder where the model was stored.
    # `cache_dir` will be the default '/root/.cache/huggingface/hub'
    if not os.path.isdir(repo_id):
        storage_folder = snapshot_download(
            repo_id=repo_id,
            revision=revision,
            library_name="fastai",
            library_version=get_fastai_version(),
        )
    else:
        storage_folder = repo_id

    _check_fastai_fastcore_pyproject_versions(storage_folder)

    from fastai.learner import load_learner

    return load_learner(os.path.join(storage_folder, "model.pkl"))


def push_to_hub_fastai(
    learner,
    repo_id: str,
    commit_message: Optional[str] = "Add model",
    private: bool = False,
    token: Optional[str] = None,
    config: Optional[dict] = None,
    **kwargs,
):
    """
    Upload learner checkpoint files to the Hub while synchronizing a local clone of the repo in
    :obj:`repo_id`.

    Args:
        learner (`Learner`):
            The `fastai.Learner' you'd like to push to the Hub.
        repo_id (`str`):
            The repository id for your model in Hub in the format of "namespace/repo_name". The namespace can be your individual account or an organization to which you have write access (for example, 'stanfordnlp/stanza-de').
        commit_message (`str`, *optional*):
            Message to commit while pushing. Will default to :obj:`"add model"`.
        private (`bool`, *optional*, defaults to `False`):
            Whether or not the repository created should be private.
        token (`str`, *optional*):
            The Hugging Face account token to use as HTTP bearer authorization for remote files. If :obj:`None`, the token will be asked by a prompt.
        config (`dict`, *optional*):
            Configuration object to be saved alongside the model weights.

    Keyword Args:
        api_endpoint (`str`, *optional*):
            The API endpoint to use when pushing the model to the hub.
        git_user (`str`, *optional*):
            Will override the ``git config user.name`` for committing and pushing files to the hub.
        git_email (`str`, *optional*):
            Will override the ``git config user.email`` for committing and pushing files to the hub.

    Returns:
        The url of the commit of your model in the given repository.

    <Tip>

    Raises the following error:

        - [`ValueError`](https://docs.python.org/3/library/exceptions.html#ValueError)
          if the user is not log on to the Hugging Face Hub.

    </Tip>
    """

    _check_fastai_fastcore_versions()

    api_endpoint: str = kwargs.get("api_endpoint", None)
    git_user: str = kwargs.get("git_user", None)
    git_email: str = kwargs.get("git_email", None)

    if token is None:
        token = HfFolder.get_token()

    if token is None:
        raise ValueError(
            "You must login to the Hugging Face Hub. There are two options: "
            "(1) Type `huggingface-cli login` in your terminal and enter your token. "
            "(2) Enter your token in the `token` argument. "
            "Your token is available in the Settings of your Hugging Face account. "
        )

    # Create repo using `HfApi()`.
    repo_url = HfApi(endpoint=api_endpoint).create_repo(
        repo_id,
        token=token,
        private=private,
        repo_type=None,
        exist_ok=True,
    )

    # If repository exists in the Hugging Face Hub then clone it locally in `repo_id`.
    repo = Repository(
        repo_id,
        clone_from=repo_url,
        use_auth_token=token,
        git_user=git_user,
        git_email=git_email,
    )
    repo.git_pull(rebase=True)

    _save_pretrained_fastai(learner, repo_id, config=config)

    return repo.push_to_hub(commit_message=commit_message)
