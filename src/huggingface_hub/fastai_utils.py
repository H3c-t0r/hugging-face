import json
import os
from pathlib import Path
from pickle import DEFAULT_PROTOCOL
from typing import Any, Dict, Optional

import packaging.version

from huggingface_hub.constants import CONFIG_NAME
from huggingface_hub.file_download import (
    _PY_VERSION,
    get_fastai_version,
    get_fastcore_version,
)
from huggingface_hub.hf_api import HfApi, HfFolder
from huggingface_hub.repository import Repository
from huggingface_hub.snapshot_download import snapshot_download


def check_fastai_fastcore_versions(
    fastai_min_version: Optional[str] = "2.4",
    fastcore_min_version: Optional[str] = "1.3.27",
):
    """
    Checks that the installed fastai and fastcore versions are compatible for pickle serialization.

    Params:
        fastai_min_version (:obj:`str`, `optional`):
            The minimum fastai version supported.
        fastcore_min_version (:obj:`str`, `optional`):
            The minimum fastcore version supported.

    Raises:
        :class:`ImportError`: if the fastai or fastcore libraries are not available or are of an invalid version.
    """

    if (get_fastcore_version() or get_fastai_version()) == "N/A":
        raise ImportError(
            f"fastai>={fastai_min_version} and fastcore>={fastcore_min_version} are required. Currently using fastai=={get_fastai_version()} and fastcore=={get_fastcore_version()}."
        )

    current_fastai_version = packaging.version.Version(get_fastai_version())
    current_fastcore_version = packaging.version.Version(get_fastcore_version())

    if current_fastai_version < packaging.version.Version(fastai_min_version):
        raise ImportError(
            f"`push_to_hub_fastai` and `from_pretrained_fastai` require a fastai>={fastai_min_version} version, but you are using fastai version {get_fastai_version()} which is incompatible. Upgrade with `pip install fastai==2.5.3`."
        )

    if current_fastcore_version < packaging.version.Version(fastcore_min_version):
        raise ImportError(
            f"`push_to_hub_fastai` and `from_pretrained_fastai` require a fastcore>={fastcore_min_version} version, but you are using fastcore version {get_fastcore_version()} which is incompatible. Upgrade with `pip install fastcore==1.3.27`."
        )


def check_fastai_fastcore_pyproject_versions(
    storage_folder: str,
    fastai_min_version: Optional[str] = "2.4",
    fastcore_min_version: Optional[str] = "1.3.27",
):
    """
    Checks that the `pyproject.toml` file in the directory `storage_folder` has fastai and fastcore versions
    that are compatible with `save_fastai_learner`, `from_pretrained_fastai` and `push_to_hub_fastai`.

    Params:
        storage_folder (:obj:`str`):
            Folder to look for the `pyproject.toml` file.
        fastai_min_version (:obj:`str`, `optional`):
            The minimum fastai version supported.
        fastcore_min_version (:obj:`str`, `optional`):
            The minimum fastcore version supported.

    Raises:
        :class: `FileNotFoundError`: if the there is no `pyproject.toml` in the repository that contains the fastai `Learner`.

        :class: `ImportError`: if the `toml` module is not installed.

        :class: `ImportError`: if the `pyproject.toml` does not indicate a version for fastai or fastcore.

        :class: `ImportError`: if the `pyproject.toml` indicates a lower than minimum supported version of fastai or fastcore.
    """

    try:
        import toml
    except ModuleNotFoundError:
        raise ImportError(
            "`push_to_hub_fastai` and `from_pretrained_fastai` require the toml module. Install it with `pip install toml`."
        )

    # Check that a `pyproject.toml` exists in the repository, and if so, get a list of required packages
    try:
        package_versions = toml.load(f"{storage_folder}/pyproject.toml")[
            "build-system"
        ]["requires"]
    except FileNotFoundError:
        raise FileNotFoundError(
            "There is no `pyproject.toml` in the repository that contains the fastai `Learner`. This is necessary to verify that your fastai and fastcore versions are compatible with those of the model you want to load."
        )

    # Check that `pyproject.toml` contains versions for fastai and fastcore. If there is no version available, it throws an error
    # Then get the fastai and fastcore versions in `pyproject.toml`. If there is none, it means that it defaults to the highest version.
    try:
        fastai_version = str(
            [package for package in package_versions if package.startswith("fastai")][0]
        )
        fastai_version = fastai_version.partition("=")[2]
    except IndexError:
        raise ImportError(
            "The repository does not have a fastai version specified in `pyproject.toml`."
        )
    try:
        fastcore_version = str(
            [package for package in package_versions if package.startswith("fastcore")][
                0
            ]
        )
        fastcore_version = fastcore_version.partition("=")[2]

    except IndexError:
        raise ImportError(
            "The repository does not have a fastcore version specified in `pyproject.toml`."
        )

    # Versions in `pyproject.toml` must be higher or equal to `fastai_min_version` and `fastcore_min_version`
    if not (
        fastai_version == ""
        or packaging.version.Version(fastai_version)
        >= packaging.version.Version(fastai_min_version)
    ):
        raise ImportError(
            f"`from_pretrained_fastai` requires fastai>={fastai_min_version} version but the model to load uses {fastai_version} which is incompatible."
        )

    if not (
        fastcore_version == ""
        or packaging.version.Version(fastcore_version)
        >= packaging.version.Version(fastcore_min_version)
    ):
        raise ImportError(
            f"`from_pretrained_fastai` requires fastcore>={fastcore_min_version} version, but you are using fastcore version {fastcore_version} which is incompatible."
        )


# Define template for auto-generated README.md
README_TEMPLATE = """---
tags:
- fastai
---

# Amazing!

Congratulations on hosting your fastai model on the Hugging Face Hub!

# Some next steps
1. Fill out this model card with more information (template below and [documentation here](https://huggingface.co/docs/hub/model-repos))!

2. Create a demo in Gradio or Streamlit using the 🤗Spaces ([documentation here](https://huggingface.co/docs/hub/spaces)).

3. Join our fastai community on the Hugging Face Discord!

Greetings fellow fastlearner 🤝!


---


# Model card

## Model description
More information needed

## Intended uses & limitations
More information needed

## Training and evaluation data
More information needed
"""

# Define template for auto-generated pyproject.toml
PYPROJECT_TEMPLATE = f"""[build-system]
requires = ["setuptools>=40.8.0", "wheel", "python={_PY_VERSION}", "fastai={get_fastai_version()}", "fastcore={get_fastcore_version()}"]
build-backend = "setuptools.build_meta:__legacy__"
"""


def _create_model_card(repo_dir: Path):
    """
    Creates a model card for the repository.

    Params:
        repo_dir (:obj:`Path`):
            Directory where model card is created.
    """
    readme_path = repo_dir / "README.md"

    if not readme_path.exists():
        with readme_path.open("w", encoding="utf-8") as f:
            f.write(README_TEMPLATE)


def _create_model_pyproject(repo_dir: Path):
    """
    Creates a `pyproject.toml` for the repository.

    Params:
        repo_dir (:obj:`Path`):
            Directory where `pyproject.toml` is created.
    """
    pyproject_path = repo_dir / "pyproject.toml"

    if not pyproject_path.exists():
        with pyproject_path.open("w", encoding="utf-8") as f:
            f.write(PYPROJECT_TEMPLATE)


def save_fastai_learner(
    learner,
    save_directory: str,
    config: Optional[Dict[str, Any]] = None,
):
    """
    Saves a fastai learner to `save_directory` in pickle format using the default pickle protocol for the version of python used.
    Apply this if you're using Learners.

    Params:
        learner (:obj:`Learner`):
            The `fastai.Learner` you'd like to save.
        save_directory (:obj:`str`):
            Specific directory in which you want to save the fastai learner.
        config (:obj:`dict`, `optional`):
            Configuration object. Will be uploaded as a .json file. Example: 'https://huggingface.co/espejelomar/fastai-pet-breeds-classification/blob/main/config.json'.

    Raises:
        :class:`RuntimeError`: if the config file provided is not a dictionary.
    """
    # Check that fastai and fastcore versions are supported.
    check_fastai_fastcore_versions()

    os.makedirs(save_directory, exist_ok=True)

    # save config
    # if user provides config then we update it with the fastai and fastcore versions in CONFIG_TEMPLATE.
    if config is not None:
        if not isinstance(config, dict):
            raise RuntimeError(
                f"Provided config should be a dict. Got: '{type(config)}'"
            )
        path = os.path.join(save_directory, CONFIG_NAME)
        with open(path, "w") as f:
            json.dump(config, f)

    # creating README.md if none exist
    _create_model_card(Path(save_directory))

    # creating pyproject.toml if none exist
    _create_model_pyproject(Path(save_directory))

    # saving learner
    # learner.export saves the model in `self.path/save_directory` and this folder should exist.
    # We create this folder and call it `fastai_path`
    fastai_path = os.path.join(learner.path, save_directory)
    os.makedirs(fastai_path, exist_ok=True)
    learner.export(
        fname=os.path.join(save_directory, "model.pkl"),
        pickle_protocol=DEFAULT_PROTOCOL,
    )

    # We move the model from `self.path/save_directory/model.pkl` to `save_directory/model.pkl`.
    os.rename(
        os.path.join(fastai_path, "model.pkl"),
        os.path.join(save_directory, "model.pkl"),
    )


def from_pretrained_fastai(
    model_id: str,
    revision: Optional[str] = None,
):
    """
    Load pretrained fastai model from the Hub.

    Params:
        model_id (:obj:`str`):
            The model id where the pickled fastai.Learner is. Example: 'espejelomar/fastai-pet-breeds-classification'.
        revision (:obj:`str`, `optional`):
            Revision at which the repo's files are downloaded. See documentation of `snapshot_download`.

    Returns:
        The `fastai.Learner` model in the `model_id` repo.
    """
    # Check that fastai and fastcore versions are supported.
    check_fastai_fastcore_versions()

    # Load the `model_id` repo.
    # `snapshot_download` returns the folder where the `model_id` repo was stored.
    # `cache_dir` will be the default '/root/.cache/huggingface/hub'
    storage_folder = snapshot_download(model_id=model_id, revision=revision)

    # Check that fastai and fastcore versions in the `model_id` repository are supported.
    check_fastai_fastcore_pyproject_versions(storage_folder)

    # Import `load_learner` from `fastai.learner`.
    from fastai.learner import load_learner

    model = load_learner(os.path.join(storage_folder, "model.pkl"))
    return model


def push_to_hub_fastai(
    learner,
    model_id: str,
    commit_message: Optional[str] = "Add model",
    private: Optional[bool] = None,
    token: Optional[str] = None,
    config: Optional[dict] = None,
    **kwargs,
):
    """
    Upload learner checkpoint files to the Hub while synchronizing a local clone of the repo in
    :obj:`model_id`.

    Params:
        learner (:obj:`Learner`):
            The `fastai.Learner' you'd like to push to the Hub.
        model_id (:obj:`str`):
            The name of the repository for your model in the Hub. The user can be your individual account (e.g. 'espejelomar/sentece-embeddings-BETO') or an organization to which you have write access (e.g. 'stanfordnlp/stanza-de').
        commit_message (:obj:`str`, `optional`):
            Message to commit while pushing. Will default to :obj:`"add model"`.
        private (:obj:`bool`, `optional`):
            Whether or not the repository created should be private (requires a paying subscription).
        token (:obj:`str`, `optional`):
            The Hugging Face account token to use as HTTP bearer authorization for remote files. If :obj:`None`, the token will be asked by a prompt.
        config (:obj:`dict`, `optional`):
            Configuration object to be saved alongside the model weights.

    Keyword Params:
        api_endpoint (:obj:`str`, `optional`):
            The API endpoint to use when pushing the model to the hub.
        git_user (:obj:`str`, `optional`):
            Will override the ``git config user.name`` for committing and pushing files to the hub.
        git_email (:obj:`str`, `optional`):
            Will override the ``git config user.email`` for committing and pushing files to the hub.

    Returns:
        The url of the commit of your model in the given repository.

    Raises:
        :class:`ValueError`: if the user is not log on to the Hugging Face Hub.
    """

    # Check that fastai and fastcore versions are supported.
    check_fastai_fastcore_versions()

    # Unpacking **kwargs.
    api_endpoint: str = kwargs.get("api_endpoint", None)
    git_user: str = kwargs.get("git_user", None)
    git_email: str = kwargs.get("git_email", None)

    # Defining token value.
    if token is None:
        token = HfFolder.get_token()

    if token is None:
        raise ValueError(
            "You must login to the Hugging Face Hub. There are two options:"
            "(1) Type `huggingface-cli login` in your terminal and enter your token."
            "(2) Enter your token in the `token` argument."
            "Your token is available in the Settings of your Hugging Face account."
        )

    # Create repo using `HfApi()`.
    repo_url = HfApi(endpoint=api_endpoint).create_repo(
        model_id,
        token=token,
        private=private,
        repo_type=None,
        exist_ok=True,
    )

    # If repository exists in the Hugging Face Hub then clone it locally in `model_id`
    repo = Repository(
        model_id,
        clone_from=repo_url,
        use_auth_token=token,
        git_user=git_user,
        git_email=git_email,
    )
    repo.git_pull(rebase=True)

    save_fastai_learner(learner, model_id, config=config)

    # Commit and push
    return repo.push_to_hub(commit_message=commit_message)
