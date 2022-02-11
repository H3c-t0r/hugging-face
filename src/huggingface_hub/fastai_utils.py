import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

import packaging.version

from huggingface_hub import ModelHubMixin
from huggingface_hub.constants import CONFIG_NAME
from huggingface_hub.file_download import get_fastai_version, get_fastcore_version
from huggingface_hub.hf_api import HfApi, HfFolder
from huggingface_hub.repository import Repository
from huggingface_hub.snapshot_download import snapshot_download


# Verify if we are using the right fastai version.
if packaging.version.Version(get_fastai_version()) < packaging.version.Version("2.4"):
    raise ImportError(
        f"`push_to_hub_fastai` and `from_pretrained_fastai` require a fastai>=2.4 version, but you are using fastai version {get_fastai_version()} which is incompatible. Upgrade with `pip install fastai==2.5.3`."
    )

# Verify if we are using the right fastcore version.
if packaging.version.Version(get_fastcore_version()) < packaging.version.Version(
    "1.3.27"
):
    raise ImportError(
        f"`push_to_hub_fastai` and `from_pretrained_fastai` require a fastcore>=1.3.27 version, but you are using fastcore version {get_fastcore_version()} which is incompatible. Upgrade with `pip install fastcore==1.3.27`."
    )

logger = logging.getLogger(__name__)

# Verify availability of `load_learner`.
try:
    from fastai.learner import Learner, load_learner
except ImportError as error:
    logger.error(
        error.__class__.__name__
        + f": `push_to_hub_fastai` and `from_pretrained_fastai` require a fastai>=2.4 version, but you are using fastai version {get_fastai_version()} which is incompatible. Run, for example, `pip install fastai==2.5.1`."
    )

# Define template for a auto-generated README.md
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

# Define template for a auto-generated config with fastai and fastcore versions
CONFIG_TEMPLATE = dict(
    fastai_version=get_fastai_version(), fastcore_version=get_fastcore_version()
)


def _create_model_card(repo_dir: Path):
    """
    Creates a model card for the repository.

    Parameters:
        repo_dir (:obj:`Path`):
            Directory where model card is created.
    """
    readme_path = repo_dir / "README.md"
    readme = ""
    if readme_path.exists():
        with readme_path.open("r", encoding="utf8") as f:
            readme = f.read()
    else:
        readme = README_TEMPLATE
    with readme_path.open("w", encoding="utf-8") as f:
        f.write(readme)


def save_fastai_learner(
    learner: Learner,
    save_directory: str,
    config: Optional[Dict[str, Any]] = None,
    **kwargs,
):
    """
    Saves a fastai learner to save_directory in pickle format. Use this if you're using Learners.

    Parameters:
        learner (:obj:`Learner`):
            The `fastai.learner` you'd like to save.
        save_directory (:obj:`str`):
            Specify directory in which you want to save the fastai learner.
        config (:obj:`dict`, `optional`):
            Configuration object. Will be uploaded as a .json file. Example: 'https://huggingface.co/espejelomar/fastai-pet-breeds-classification/blob/main/config.json'.

    Keyword Parameters:
        pickle_protocol (:obj:`int`, `optional`):
            Pickle protocol passed to torch.save. Refer to pickle documentation.

    """
    # Unpacking **model_save_kwargs
    pickle_protocol: int = kwargs.get("pickle_protocol", 2)

    os.makedirs(save_directory, exist_ok=True)

    # saving config
    # if user provides config then we update it with the fastai and fastcore versions in CONFIG_TEMPLATE.
    if config is not None:
        if not isinstance(config, dict):
            raise RuntimeError(
                f"Provided config should be a dict. Got: '{type(config)}'"
            )
        path = os.path.join(save_directory, CONFIG_NAME)
        with open(path, "w") as f:
            json.dump({**config, **CONFIG_TEMPLATE}, f)
    else:
        path = os.path.join(save_directory, CONFIG_NAME)
        with open(path, "w") as f:
            json.dump(CONFIG_TEMPLATE, f)

    # creating README.md if none exist
    _create_model_card(Path(save_directory))

    # saving learner
    learner.export(
        fname=os.path.join(save_directory, "model.pkl"), pickle_protocol=pickle_protocol
    )


def from_pretrained_fastai(*args, **kwargs):
    return FastaiModelHubMixin.from_pretrained(*args, **kwargs)


def push_to_hub_fastai(
    learner: Learner,
    repo_path_or_name: Optional[str] = None,
    commit_message: Optional[str] = "Add model",
    private: Optional[bool] = None,
    use_auth_token: Optional[Union[bool, str]] = True,
    config: Optional[dict] = None,
    **model_save_kwargs,
):
    """
    Upload learner checkpoint files to the Hub while synchronizing a local clone of the repo in
    :obj:`repo_path_or_name`.

    Parameters:
        learner (:obj:`Learner`):
            The `fastai.Learner' you'd like to push to the Hub.
        repo_path_or_name (:obj:`str`, `optional`):
            Can either be a repository name for your model in the Hub or a path to a local folder (in
            which case the repository will have the name of that local folder). If not specified, will default to
            the name given by :obj:`repo_url` and a local directory with that name will be created.
        commit_message (:obj:`str`, `optional`):
            Message to commit while pushing. Will default to :obj:`"add model"`.
        private (:obj:`bool`, `optional`):
            Whether or not the repository created should be private (requires a paying subscription).
        use_auth_token (:obj:`bool` or :obj:`str`, `optional`):
            The token to use as HTTP bearer authorization for remote files. If :obj:`True`, will use the token
            generated when running :obj:`transformers-cli login` (stored in :obj:`~/.huggingface`). Will default to
            :obj:`True`.
        config (:obj:`dict`, `optional`):
            Configuration object to be saved alongside the model weights.

    Keyword Parameters:
        repo_url (:obj:`str`, `optional`):
            Specify this in case you want to push to an existing repository in the hub. If unspecified, a new
            repository will be created in your namespace (unless you specify an :obj:`organization`) with
            :obj:`repo_name`.
        organization (:obj:`str`, `optional`):
            Organization in which you want to push your model or tokenizer (you must be a member of this
            organization).
        api_endpoint (:obj:`str`, `optional`):
            The API endpoint to use when pushing the model to the hub.
        git_user (:obj:`str`, `optional`):
            Will override the ``git config user.name`` for committing and pushing files to the hub.
        git_email (:obj:`str`, `optional`):
            Will override the ``git config user.email`` for committing and pushing files to the hub.
        pickle_protocol (:obj:`int`, `optional`):
            Pickle protocol passed to torch.save. Refer to pickle documentation.

    Returns:
        The url of the commit of your model in the given repository.
    """
    # Unpacking **model_save_kwargs
    repo_url: str = model_save_kwargs.get("repo_url", None)
    organization: str = model_save_kwargs.get("organization", None)
    api_endpoint: str = model_save_kwargs.get("api_endpoint", None)
    git_user: str = model_save_kwargs.get("git_user", None)
    git_email: str = model_save_kwargs.get("git_email", None)
    pickle_protocol: int = model_save_kwargs.get("pickle_protocol", 2)

    if repo_path_or_name is None and repo_url is None:
        raise ValueError("You need to specify a `repo_path_or_name` or a `repo_url`.")

    if isinstance(use_auth_token, bool) and use_auth_token:
        token = HfFolder.get_token()
    elif isinstance(use_auth_token, str):
        token = use_auth_token
    else:
        token = None

    if token is None:
        raise ValueError(
            "You must login to the Hugging Face Hub on this computer by typing `huggingface-cli login` and "
            "entering your credentials to use `use_auth_token=True`. Alternatively, you can pass your own "
            "token as the `use_auth_token` argument."
        )

    if repo_path_or_name is None:
        repo_path_or_name = repo_url.split("/")[-1]

    # If no URL is passed and there's no path to a directory containing files, create a repo
    if repo_url is None and not os.path.exists(repo_path_or_name):
        repo_name = Path(repo_path_or_name).name
        repo_url = HfApi(endpoint=api_endpoint).create_repo(
            token,
            repo_name,
            organization=organization,
            private=private,
            repo_type=None,
            exist_ok=True,
        )

    repo = Repository(
        repo_path_or_name,
        clone_from=repo_url,
        use_auth_token=use_auth_token,
        git_user=git_user,
        git_email=git_email,
    )
    repo.git_pull(rebase=True)

    save_fastai_learner(
        learner, repo_path_or_name, config=config, pickle_protocol=pickle_protocol
    )

    # Commit and push!
    # repo.git_add(auto_lfs_track=True)
    return repo.push_to_hub(commit_message=commit_message)


class FastaiModelHubMixin(ModelHubMixin):
    def __init__(self, *args, **kwargs):
        """
        Mixin class to implement model download and upload from fastai learners.

        # Downloading Learner from the Hugging Face Hub:
        Example::

            >>> from huggingface_hub import from_pretrained_fastai
            >>> model = from_pretrained_fastai("username/mymodel@main")
        """

    def _save_pretrained(self, save_directory):
        save_fastai_learner(self, save_directory)

    @classmethod
    def _from_pretrained(
        cls,
        model_id,
        revision,
        cache_dir,
        force_download,
        proxies,
        resume_download,
        local_files_only,
        use_auth_token,
        **model_kwargs,
    ):
        """
        Call save_fastai_learner function so both the mixin and functional APIs stay in sync.
        """

        cfg = model_kwargs.pop("config", None)

        # Root is either a local filepath matching model_id or a cached snapshot
        if not os.path.isdir(model_id):
            storage_folder = snapshot_download(
                repo_id=model_id, revision=revision, cache_dir=cache_dir
            )
        else:
            storage_folder = model_id

        # Using the pickle document in the downloaded list
        docs = os.listdir(storage_folder)
        for doc in docs:
            if doc.endswith(".pkl"):
                pickle = doc
                break

        logger.info(
            f"Using `fastai.learner` stored in {os.path.join(model_id, pickle)}."
        )
        print(f"Using `fastai.learner` stored in {os.path.join(model_id, pickle)}.")

        model = load_learner(os.path.join(storage_folder, pickle))
        model.config = cfg

        return model
