# Copyright 2020 The HuggingFace Team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import re
import shutil
import subprocess
import tempfile
import time
import types
import unittest
import warnings
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import List
from unittest.mock import Mock, patch
from urllib.parse import quote

import pytest

import requests
from huggingface_hub import Repository, SpaceHardware, SpaceStage
from huggingface_hub._commit_api import (
    CommitOperationAdd,
    CommitOperationDelete,
    fetch_upload_modes,
)
from huggingface_hub._login import _login, _set_store_as_git_credential_helper_globally
from huggingface_hub.community import DiscussionComment, DiscussionWithDetails
from huggingface_hub.constants import (
    REPO_TYPE_DATASET,
    REPO_TYPE_MODEL,
    REPO_TYPE_SPACE,
    SPACES_SDK_TYPES,
)
from huggingface_hub.file_download import cached_download, hf_hub_download
from huggingface_hub.hf_api import (
    USERNAME_PLACEHOLDER,
    CommitInfo,
    DatasetInfo,
    DatasetSearchArguments,
    HfApi,
    MetricInfo,
    ModelInfo,
    ModelSearchArguments,
    RepoFile,
    RepoUrl,
    SpaceInfo,
    erase_from_credential_store,
    read_from_credential_store,
    repo_type_and_id_from_hf_id,
)
from huggingface_hub.utils import (
    BadRequestError,
    EntryNotFoundError,
    HfFolder,
    HfHubHTTPError,
    RepositoryNotFoundError,
    RevisionNotFoundError,
    logging,
)
from huggingface_hub.utils.endpoint_helpers import (
    DatasetFilter,
    ModelFilter,
    _filter_emissions,
)
from requests.exceptions import HTTPError

from .testing_constants import (
    ENDPOINT_STAGING,
    ENDPOINT_STAGING_BASIC_AUTH,
    FULL_NAME,
    TOKEN,
    USER,
)
from .testing_utils import (
    DUMMY_DATASET_ID,
    DUMMY_DATASET_ID_REVISION_ONE_SPECIFIC_COMMIT,
    DUMMY_MODEL_ID,
    DUMMY_MODEL_ID_REVISION_ONE_SPECIFIC_COMMIT,
    SAMPLE_DATASET_IDENTIFIER,
    expect_deprecation,
    repo_name,
    require_git_lfs,
    retry_endpoint,
    rmtree_with_retry,
    use_tmp_repo,
    with_production_testing,
)


logger = logging.get_logger(__name__)

dataset_repo_name = partial(repo_name, prefix="my-dataset")
space_repo_name = partial(repo_name, prefix="my-space")
large_file_repo_name = partial(repo_name, prefix="my-model-largefiles")

WORKING_REPO_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures/working_repo"
)
LARGE_FILE_14MB = "https://cdn-media.huggingface.co/lfs-largefiles/progit.epub"
LARGE_FILE_18MB = "https://cdn-media.huggingface.co/lfs-largefiles/progit.pdf"


class HfApiCommonTest(unittest.TestCase):
    _api = HfApi(endpoint=ENDPOINT_STAGING)


class HfApiLoginTest(HfApiCommonTest):
    @expect_deprecation("erase_from_credential_store")
    def setUp(self) -> None:
        erase_from_credential_store(USERNAME_PLACEHOLDER)

    @classmethod
    @expect_deprecation("set_access_token")
    def tearDownClass(cls) -> None:
        cls._api.set_access_token(TOKEN)

    @expect_deprecation("read_from_credential_store")
    def test_login_git_credentials(self):
        self.assertTupleEqual(
            read_from_credential_store(USERNAME_PLACEHOLDER), (None, None)
        )
        self._api.set_access_token(TOKEN)
        self.assertTupleEqual(
            read_from_credential_store(USERNAME_PLACEHOLDER),
            (USERNAME_PLACEHOLDER, TOKEN),
        )
        erase_from_credential_store(username=USERNAME_PLACEHOLDER)
        self.assertTupleEqual(
            read_from_credential_store(USERNAME_PLACEHOLDER), (None, None)
        )

    @expect_deprecation("read_from_credential_store")
    def test_login_cli(self):
        self._api.set_access_token(TOKEN)
        self.assertTupleEqual(
            read_from_credential_store(USERNAME_PLACEHOLDER),
            (USERNAME_PLACEHOLDER, TOKEN),
        )
        erase_from_credential_store(username=USERNAME_PLACEHOLDER)
        self.assertTupleEqual(
            read_from_credential_store(USERNAME_PLACEHOLDER), (None, None)
        )

        _set_store_as_git_credential_helper_globally()
        _login(token=TOKEN, add_to_git_credential=True)
        self.assertTupleEqual(
            read_from_credential_store(USERNAME_PLACEHOLDER),
            (USERNAME_PLACEHOLDER, TOKEN),
        )
        erase_from_credential_store(username=USERNAME_PLACEHOLDER)
        self.assertTupleEqual(
            read_from_credential_store(USERNAME_PLACEHOLDER), (None, None)
        )

    def test_login_cli_org_fail(self):
        with pytest.raises(
            ValueError, match="You must use your personal account token."
        ):
            _login(token="api_org_dummy_token", add_to_git_credential=True)


class HfApiCommonTestWithLogin(HfApiCommonTest):
    @classmethod
    @expect_deprecation("set_access_token")
    def setUpClass(cls):
        """
        Share this valid token in all tests below.
        """
        cls._token = TOKEN
        cls._api.token = TOKEN
        cls._api.set_access_token(TOKEN)


@retry_endpoint
def test_repo_id_no_warning():
    # tests that passing repo_id as positional arg doesn't raise any warnings
    # for {create, delete}_repo and update_repo_visibility
    api = HfApi(endpoint=ENDPOINT_STAGING, token=TOKEN)
    REPO_NAME = repo_name("crud")

    args = [
        ("create_repo", {}),
        ("update_repo_visibility", {"private": False}),
        ("delete_repo", {}),
    ]

    for method, kwargs in args:
        with warnings.catch_warnings(record=True) as record:
            getattr(api, method)(REPO_NAME, repo_type=REPO_TYPE_MODEL, **kwargs)
        assert not len(record)


class HfApiEndpointsTest(HfApiCommonTestWithLogin):
    def test_whoami_with_passing_token(self):
        info = self._api.whoami(token=self._token)
        self.assertEqual(info["name"], USER)
        self.assertEqual(info["fullname"], FULL_NAME)
        self.assertIsInstance(info["orgs"], list)
        valid_org = [org for org in info["orgs"] if org["name"] == "valid_org"][0]
        self.assertIsInstance(valid_org["apiToken"], str)

    @patch("huggingface_hub.utils._headers.HfFolder")
    def test_whoami_with_implicit_token_from_login(self, mock_HfFolder: Mock) -> None:
        """Test using `whoami` after a `huggingface-cli login`."""
        mock_HfFolder().get_token.return_value = self._token

        with patch.object(self._api, "token", None):  # no default token
            info = self._api.whoami()
        self.assertEqual(info["name"], USER)

    @patch("huggingface_hub.utils._headers.HfFolder")
    def test_whoami_with_implicit_token_from_hf_api(self, mock_HfFolder: Mock) -> None:
        """Test using `whoami` with token from the HfApi client."""
        info = self._api.whoami()
        self.assertEqual(info["name"], USER)
        mock_HfFolder().get_token.assert_not_called()

    @retry_endpoint
    def test_delete_repo_error_message(self):
        # test for #751
        # See https://github.com/huggingface/huggingface_hub/issues/751
        with self.assertRaisesRegex(
            requests.exceptions.HTTPError,
            re.compile(
                r"404 Client Error(.+)\(Request ID: .+\)(.*)Repository Not Found",
                flags=re.DOTALL,
            ),
        ):
            self._api.delete_repo("repo-that-does-not-exist")

    @retry_endpoint
    def test_create_update_and_delete_repo(self):
        REPO_NAME = repo_name("crud")
        self._api.create_repo(repo_id=REPO_NAME)
        res = self._api.update_repo_visibility(repo_id=REPO_NAME, private=True)
        self.assertTrue(res["private"])
        res = self._api.update_repo_visibility(repo_id=REPO_NAME, private=False)
        self.assertFalse(res["private"])
        self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_create_update_and_delete_model_repo(self):
        REPO_NAME = repo_name("crud")
        self._api.create_repo(repo_id=REPO_NAME, repo_type=REPO_TYPE_MODEL)
        res = self._api.update_repo_visibility(
            repo_id=REPO_NAME, private=True, repo_type=REPO_TYPE_MODEL
        )
        self.assertTrue(res["private"])
        res = self._api.update_repo_visibility(
            repo_id=REPO_NAME, private=False, repo_type=REPO_TYPE_MODEL
        )
        self.assertFalse(res["private"])
        self._api.delete_repo(repo_id=REPO_NAME, repo_type=REPO_TYPE_MODEL)

    @retry_endpoint
    def test_create_update_and_delete_dataset_repo(self):
        DATASET_REPO_NAME = dataset_repo_name("crud")
        self._api.create_repo(repo_id=DATASET_REPO_NAME, repo_type=REPO_TYPE_DATASET)
        res = self._api.update_repo_visibility(
            repo_id=DATASET_REPO_NAME, private=True, repo_type=REPO_TYPE_DATASET
        )
        self.assertTrue(res["private"])
        res = self._api.update_repo_visibility(
            repo_id=DATASET_REPO_NAME, private=False, repo_type=REPO_TYPE_DATASET
        )
        self.assertFalse(res["private"])
        self._api.delete_repo(repo_id=DATASET_REPO_NAME, repo_type=REPO_TYPE_DATASET)

    @unittest.skip(
        "Create repo fails on staging endpoint. See"
        " https://huggingface.slack.com/archives/C02EMARJ65P/p1666795928977419"
        " (internal link)."
    )
    @retry_endpoint
    def test_create_update_and_delete_space_repo(self):
        SPACE_REPO_NAME = space_repo_name("failing")
        with pytest.raises(ValueError, match=r"No space_sdk provided.*"):
            self._api.create_repo(
                repo_id=SPACE_REPO_NAME, repo_type=REPO_TYPE_SPACE, space_sdk=None
            )
        with pytest.raises(ValueError, match=r"Invalid space_sdk.*"):
            self._api.create_repo(
                repo_id=SPACE_REPO_NAME, repo_type=REPO_TYPE_SPACE, space_sdk="asdfasdf"
            )

        for sdk in SPACES_SDK_TYPES:
            SPACE_REPO_NAME = space_repo_name(sdk)
            self._api.create_repo(
                repo_id=SPACE_REPO_NAME, repo_type=REPO_TYPE_SPACE, space_sdk=sdk
            )
            res = self._api.update_repo_visibility(
                repo_id=SPACE_REPO_NAME, private=True, repo_type=REPO_TYPE_SPACE
            )
            self.assertTrue(res["private"])
            res = self._api.update_repo_visibility(
                repo_id=SPACE_REPO_NAME, private=False, repo_type=REPO_TYPE_SPACE
            )
            self.assertFalse(res["private"])
            self._api.delete_repo(repo_id=SPACE_REPO_NAME, repo_type=REPO_TYPE_SPACE)

    @retry_endpoint
    def test_move_repo_normal_usage(self):
        repo_id = f"{USER}/{repo_name()}"
        new_repo_id = f"{USER}/{repo_name()}"

        for repo_type in [None, REPO_TYPE_MODEL, REPO_TYPE_DATASET, REPO_TYPE_SPACE]:
            self._api.create_repo(
                repo_id=repo_id,
                repo_type=repo_type,
                space_sdk="static" if repo_type == REPO_TYPE_SPACE else None,
            )
            # Should raise an error if it fails
            self._api.move_repo(from_id=repo_id, to_id=new_repo_id, repo_type=repo_type)
            self._api.delete_repo(repo_id=new_repo_id, repo_type=repo_type)

    def test_move_repo_target_already_exists(self) -> None:
        repo_id_1 = f"{USER}/{repo_name()}"
        repo_id_2 = f"{USER}/{repo_name()}"

        self._api.create_repo(repo_id=repo_id_1)
        self._api.create_repo(repo_id=repo_id_2)

        with pytest.raises(
            HfHubHTTPError, match=r"A model repository called .* already exists"
        ):
            self._api.move_repo(
                from_id=repo_id_1, to_id=repo_id_2, repo_type=REPO_TYPE_MODEL
            )

        self._api.delete_repo(repo_id=repo_id_1)
        self._api.delete_repo(repo_id=repo_id_2)

    def test_move_repo_invalid_repo_id(self) -> None:
        """Test from_id and to_id must be in the form `"namespace/repo_name"`."""
        with pytest.raises(ValueError, match=r"Invalid repo_id*"):
            self._api.move_repo(from_id="namespace/repo_name", to_id="invalid_repo_id")

        with pytest.raises(ValueError, match=r"Invalid repo_id*"):
            self._api.move_repo(from_id="invalid_repo_id", to_id="namespace/repo_name")


class CommitApiTest(HfApiCommonTestWithLogin):
    def setUp(self) -> None:
        super().setUp()
        self.tmp_dir = tempfile.mkdtemp()
        self.tmp_file = os.path.join(self.tmp_dir, "temp")
        self.tmp_file_content = "Content of the file"
        with open(self.tmp_file, "w+") as f:
            f.write(self.tmp_file_content)
        os.makedirs(os.path.join(self.tmp_dir, "nested"))
        self.nested_tmp_file = os.path.join(self.tmp_dir, "nested", "file.bin")
        with open(self.nested_tmp_file, "wb+") as f:
            f.truncate(1024 * 1024)

        self.addCleanup(rmtree_with_retry, self.tmp_dir)

    @retry_endpoint
    def test_upload_file_validation(self):
        REPO_NAME = repo_name("upload")
        with self.assertRaises(ValueError, msg="Wrong repo type"):
            self._api.upload_file(
                path_or_fileobj=self.tmp_file,
                path_in_repo="README.md",
                repo_id=f"{USER}/{REPO_NAME}",
                repo_type="this type does not exist",
            )

    def test_commit_operation_validation(self):
        with open(self.tmp_file, "rt") as ftext:
            with self.assertRaises(
                ValueError,
                msg="If you passed a file-like object, make sure it is in binary mode",
            ):
                CommitOperationAdd(
                    path_or_fileobj=ftext, path_in_repo="README.md"  # type: ignore
                )

        with self.assertRaises(
            ValueError, msg="path_or_fileobj is str but does not point to a file"
        ):
            CommitOperationAdd(
                path_or_fileobj=os.path.join(self.tmp_dir, "nofile.pth"),
                path_in_repo="README.md",
            )

    @retry_endpoint
    def test_upload_file_str_path(self):
        REPO_NAME = repo_name("str_path")
        self._api.create_repo(repo_id=REPO_NAME)
        try:
            return_val = self._api.upload_file(
                path_or_fileobj=self.tmp_file,
                path_in_repo="temp/new_file.md",
                repo_id=f"{USER}/{REPO_NAME}",
            )
            self.assertEqual(
                return_val,
                f"{self._api.endpoint}/{USER}/{REPO_NAME}/blob/main/temp/new_file.md",
            )
            url = "{}/{user}/{repo}/resolve/main/temp/new_file.md".format(
                ENDPOINT_STAGING,
                user=USER,
                repo=REPO_NAME,
            )
            filepath = cached_download(
                url, force_download=True, legacy_cache_layout=True
            )
            with open(filepath) as downloaded_file:
                content = downloaded_file.read()
            self.assertEqual(content, self.tmp_file_content)

        except Exception as err:
            self.fail(err)
        finally:
            self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_upload_file_pathlib_path(self):
        """Regression test for https://github.com/huggingface/huggingface_hub/issues/1246."""
        repo_id = f"{USER}/{repo_name()}"
        self._api.create_repo(repo_id=repo_id)
        self._api.upload_file(
            path_or_fileobj=Path(self.tmp_file),
            path_in_repo="README.md",
            repo_id=repo_id,
        )
        self.assertIn("README.md", self._api.list_repo_files(repo_id=repo_id))
        self._api.delete_repo(repo_id=repo_id)

    @retry_endpoint
    def test_upload_file_fileobj(self):
        REPO_NAME = repo_name("fileobj")
        self._api.create_repo(repo_id=REPO_NAME)
        try:
            with open(self.tmp_file, "rb") as filestream:
                return_val = self._api.upload_file(
                    path_or_fileobj=filestream,
                    path_in_repo="temp/new_file.md",
                    repo_id=f"{USER}/{REPO_NAME}",
                )
            self.assertEqual(
                return_val,
                f"{self._api.endpoint}/{USER}/{REPO_NAME}/blob/main/temp/new_file.md",
            )
            url = "{}/{user}/{repo}/resolve/main/temp/new_file.md".format(
                ENDPOINT_STAGING, user=USER, repo=REPO_NAME
            )
            filepath = cached_download(
                url, force_download=True, legacy_cache_layout=True
            )
            with open(filepath) as downloaded_file:
                content = downloaded_file.read()
            self.assertEqual(content, self.tmp_file_content)

        except Exception as err:
            self.fail(err)
        finally:
            self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_upload_file_bytesio(self):
        REPO_NAME = repo_name("bytesio")
        self._api.create_repo(repo_id=REPO_NAME)
        try:
            filecontent = BytesIO(b"File content, but in bytes IO")
            return_val = self._api.upload_file(
                path_or_fileobj=filecontent,
                path_in_repo="temp/new_file.md",
                repo_id=f"{USER}/{REPO_NAME}",
            )
            self.assertEqual(
                return_val,
                f"{self._api.endpoint}/{USER}/{REPO_NAME}/blob/main/temp/new_file.md",
            )

            url = "{}/{user}/{repo}/resolve/main/temp/new_file.md".format(
                ENDPOINT_STAGING, user=USER, repo=REPO_NAME
            )
            filepath = cached_download(
                url, force_download=True, legacy_cache_layout=True
            )
            with open(filepath) as downloaded_file:
                content = downloaded_file.read()
            self.assertEqual(content, filecontent.getvalue().decode())

        except Exception as err:
            self.fail(err)
        finally:
            self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_create_repo_return_value(self):
        REPO_NAME = repo_name("org")
        url = self._api.create_repo(repo_id=REPO_NAME)
        self.assertIsInstance(url, str)
        self.assertIsInstance(url, RepoUrl)
        self.assertEqual(url.repo_id, f"{USER}/{REPO_NAME}")
        self._api.delete_repo(repo_id=url.repo_id)

    @retry_endpoint
    def test_create_repo_org_token_fail(self):
        REPO_NAME = repo_name("org")
        with pytest.raises(
            ValueError, match="You must use your personal account token."
        ):
            self._api.create_repo(repo_id=REPO_NAME, token="api_org_dummy_token")

    @retry_endpoint
    def test_create_repo_org_token_none_fail(self):
        HfFolder.save_token("api_org_dummy_token")
        with pytest.raises(
            ValueError, match="You must use your personal account token."
        ):
            with patch.object(self._api, "token", None):  # no default token
                self._api.create_repo(repo_id=repo_name("org"))

    @retry_endpoint
    def test_upload_buffer(self):
        REPO_NAME = repo_name("buffer")
        self._api.create_repo(repo_id=REPO_NAME)
        try:
            buffer = BytesIO()
            buffer.write(self.tmp_file_content.encode())
            return_val = self._api.upload_file(
                path_or_fileobj=buffer.getvalue(),
                path_in_repo="temp/new_file.md",
                repo_id=f"{USER}/{REPO_NAME}",
            )
            self.assertEqual(
                return_val,
                f"{self._api.endpoint}/{USER}/{REPO_NAME}/blob/main/temp/new_file.md",
            )

            url = "{}/{user}/{repo}/resolve/main/temp/new_file.md".format(
                ENDPOINT_STAGING, user=USER, repo=REPO_NAME
            )
            filepath = cached_download(
                url, force_download=True, legacy_cache_layout=True
            )
            with open(filepath) as downloaded_file:
                content = downloaded_file.read()
            self.assertEqual(content, self.tmp_file_content)

        except Exception as err:
            self.fail(err)
        finally:
            self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_upload_file_create_pr(self):
        REPO_NAME = repo_name("buffer")
        pr_revision = quote("refs/pr/1", safe="")
        self._api.create_repo(repo_id=REPO_NAME)
        try:
            buffer = BytesIO()
            buffer.write(self.tmp_file_content.encode())
            return_val = self._api.upload_file(
                path_or_fileobj=buffer.getvalue(),
                path_in_repo="temp/new_file.md",
                repo_id=f"{USER}/{REPO_NAME}",
                create_pr=True,
            )
            self.assertEqual(
                return_val,
                f"{self._api.endpoint}/{USER}/{REPO_NAME}/blob/{pr_revision}/temp/new_file.md",
            )

            url = "{}/{user}/{repo}/resolve/{revision}/temp/new_file.md".format(
                ENDPOINT_STAGING, revision=pr_revision, user=USER, repo=REPO_NAME
            )
            filepath = cached_download(
                url, force_download=True, legacy_cache_layout=True
            )
            with open(filepath) as downloaded_file:
                content = downloaded_file.read()
            self.assertEqual(content, self.tmp_file_content)

        except Exception as err:
            self.fail(err)
        finally:
            self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_delete_file(self):
        REPO_NAME = repo_name("delete")
        self._api.create_repo(repo_id=REPO_NAME)
        try:
            self._api.upload_file(
                path_or_fileobj=self.tmp_file,
                path_in_repo="temp/new_file.md",
                repo_id=f"{USER}/{REPO_NAME}",
            )
            self._api.delete_file(
                path_in_repo="temp/new_file.md", repo_id=f"{USER}/{REPO_NAME}"
            )

            with self.assertRaises(HTTPError):
                # Should raise a 404
                hf_hub_download(f"{USER}/{REPO_NAME}", "temp/new_file.md")

        except Exception as err:
            self.fail(err)
        finally:
            self._api.delete_repo(repo_id=REPO_NAME)

    def test_get_full_repo_name(self):
        repo_name_with_no_org = self._api.get_full_repo_name("model")
        self.assertEqual(repo_name_with_no_org, f"{USER}/model")

        repo_name_with_no_org = self._api.get_full_repo_name(
            "model", organization="org"
        )
        self.assertEqual(repo_name_with_no_org, "org/model")

    @retry_endpoint
    def test_upload_folder(self):
        for private in (False, True):
            visibility = "private" if private else "public"
            with self.subTest(f"{visibility} repo"):
                REPO_NAME = repo_name(f"upload_folder_{visibility}")
                self._api.create_repo(
                    repo_id=REPO_NAME, private=private, exist_ok=False
                )
                try:
                    url = self._api.upload_folder(
                        folder_path=self.tmp_dir,
                        path_in_repo="temp/dir",
                        repo_id=f"{USER}/{REPO_NAME}",
                    )
                    self.assertEqual(
                        url,
                        f"{self._api.endpoint}/{USER}/{REPO_NAME}/tree/main/temp/dir",
                    )
                    for rpath in ["temp", "nested/file.bin"]:
                        local_path = os.path.join(self.tmp_dir, rpath)
                        remote_path = f"temp/dir/{rpath}"
                        filepath = hf_hub_download(
                            repo_id=f"{USER}/{REPO_NAME}",
                            filename=remote_path,
                            revision="main",
                            use_auth_token=self._token,
                        )
                        assert filepath is not None
                        with open(filepath, "rb") as downloaded_file:
                            content = downloaded_file.read()
                        with open(local_path, "rb") as local_file:
                            expected_content = local_file.read()
                        self.assertEqual(content, expected_content)

                    # Re-uploading the same folder twice should be fine
                    self._api.upload_folder(
                        folder_path=self.tmp_dir,
                        path_in_repo="temp/dir",
                        repo_id=f"{USER}/{REPO_NAME}",
                    )
                except Exception as err:
                    self.fail(err)
                finally:
                    self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_upload_folder_create_pr(self):
        pr_revision = quote("refs/pr/1", safe="")
        for private in (False, True):
            visibility = "private" if private else "public"
            with self.subTest(f"{visibility} repo"):
                REPO_NAME = repo_name(f"upload_folder_{visibility}")
                self._api.create_repo(
                    repo_id=REPO_NAME, private=private, exist_ok=False
                )
                try:
                    return_val = self._api.upload_folder(
                        folder_path=self.tmp_dir,
                        path_in_repo="temp/dir",
                        repo_id=f"{USER}/{REPO_NAME}",
                        create_pr=True,
                    )
                    self.assertEqual(
                        return_val,
                        f"{self._api.endpoint}/{USER}/{REPO_NAME}/tree/{pr_revision}/temp/dir",
                    )
                    for rpath in ["temp", "nested/file.bin"]:
                        local_path = os.path.join(self.tmp_dir, rpath)
                        remote_path = f"temp/dir/{rpath}"
                        filepath = hf_hub_download(
                            repo_id=f"{USER}/{REPO_NAME}",
                            filename=remote_path,
                            revision="refs/pr/1",
                            use_auth_token=self._token,
                        )
                        assert filepath is not None
                        with open(filepath, "rb") as downloaded_file:
                            content = downloaded_file.read()
                        with open(local_path, "rb") as local_file:
                            expected_content = local_file.read()
                        self.assertEqual(content, expected_content)
                except Exception as err:
                    self.fail(err)
                finally:
                    self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_upload_folder_default_path_in_repo(self):
        REPO_NAME = repo_name("upload_folder_to_root")
        self._api.create_repo(repo_id=REPO_NAME, exist_ok=False)
        url = self._api.upload_folder(
            folder_path=self.tmp_dir, repo_id=f"{USER}/{REPO_NAME}"
        )
        # URL to root of repository
        self.assertEqual(url, f"{self._api.endpoint}/{USER}/{REPO_NAME}/tree/main/")

    @retry_endpoint
    def test_create_commit_create_pr(self):
        REPO_NAME = repo_name("create_commit_create_pr")
        self._api.create_repo(repo_id=REPO_NAME, exist_ok=False)
        try:
            self._api.upload_file(
                path_or_fileobj=self.tmp_file,
                path_in_repo="temp/new_file.md",
                repo_id=f"{USER}/{REPO_NAME}",
            )
            operations = [
                CommitOperationDelete(path_in_repo="temp/new_file.md"),
                CommitOperationAdd(
                    path_in_repo="buffer", path_or_fileobj=b"Buffer data"
                ),
            ]
            resp = self._api.create_commit(
                operations=operations,
                commit_message="Test create_commit",
                repo_id=f"{USER}/{REPO_NAME}",
                create_pr=True,
            )

            # Check commit info
            self.assertIsInstance(resp, CommitInfo)
            commit_id = resp.oid
            self.assertIn("pr_revision='refs/pr/1'", str(resp))
            self.assertIsInstance(commit_id, str)
            self.assertGreater(len(commit_id), 0)
            self.assertEqual(
                resp.commit_url,
                f"{self._api.endpoint}/{USER}/{REPO_NAME}/commit/{commit_id}",
            )
            self.assertEqual(resp.commit_message, "Test create_commit")
            self.assertEqual(resp.commit_description, "")
            self.assertEqual(
                resp.pr_url,
                f"{self._api.endpoint}/{USER}/{REPO_NAME}/discussions/1",
            )
            self.assertEqual(resp.pr_num, 1)
            self.assertEqual(resp.pr_revision, "refs/pr/1")

            with self.assertRaises(HTTPError) as ctx:
                # Should raise a 404
                hf_hub_download(
                    f"{USER}/{REPO_NAME}", "buffer", use_auth_token=self._token
                )
                self.assertEqual(ctx.exception.response.status_code, 404)
            filepath = hf_hub_download(
                filename="buffer",
                repo_id=f"{USER}/{REPO_NAME}",
                use_auth_token=self._token,
                revision="refs/pr/1",
            )
            self.assertTrue(filepath is not None)
            with open(filepath, "rb") as downloaded_file:
                content = downloaded_file.read()
            self.assertEqual(content, b"Buffer data")
        except Exception as err:
            self.fail(err)
        finally:
            self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_create_commit_create_pr_against_branch(self):
        repo_id = f"{USER}/{repo_name()}"

        # Create repo and create a non-main branch
        self._api.create_repo(repo_id=repo_id, exist_ok=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Repository(local_dir=tmpdir, clone_from=repo_id, token=TOKEN)
            repo.git_checkout("test_branch", create_branch_ok=True)
            head = repo.git_head_hash()
            repo.git_push("origin test_branch")

        # Create PR against non-main branch works
        resp = self._api.create_commit(
            operations=[],
            commit_message="PR against existing branch",
            repo_id=repo_id,
            revision="test_branch",
            create_pr=True,
        )
        self.assertIsInstance(resp, CommitInfo)

        # Create PR against a oid fails
        with self.assertRaises(RevisionNotFoundError):
            self._api.create_commit(
                operations=[],
                commit_message="PR against a oid",
                repo_id=repo_id,
                revision=head,
                create_pr=True,
            )

        # Create PR against a non-existing branch fails
        with self.assertRaises(RevisionNotFoundError):
            self._api.create_commit(
                operations=[],
                commit_message="PR against missing branch",
                repo_id=repo_id,
                revision="missing_branch",
                create_pr=True,
            )

        # Cleanup
        self._api.delete_repo(repo_id=repo_id)

    @retry_endpoint
    def test_create_commit_create_pr_on_foreign_repo(self):
        # Repo on which we don't have right
        # We must be able to create a PR on it
        self._api.create_commit(
            operations=[
                CommitOperationAdd(
                    path_in_repo="regular.txt", path_or_fileobj=b"File content"
                ),
                CommitOperationAdd(
                    path_in_repo="lfs.pkl", path_or_fileobj=b"File content"
                ),
            ],
            commit_message="PR on foreign repo",
            repo_id="datasets_server_org/repo_for_huggingface_hub_ci_with_prs",
            create_pr=True,
        )

    @retry_endpoint
    def test_create_commit(self):
        for private in (False, True):
            visibility = "private" if private else "public"
            with self.subTest(f"{visibility} repo"):
                REPO_NAME = repo_name(f"create_commit_{visibility}")
                self._api.create_repo(
                    repo_id=REPO_NAME, private=private, exist_ok=False
                )
                try:
                    self._api.upload_file(
                        path_or_fileobj=self.tmp_file,
                        path_in_repo="temp/new_file.md",
                        repo_id=f"{USER}/{REPO_NAME}",
                    )
                    with open(self.tmp_file, "rb") as fileobj:
                        operations = [
                            CommitOperationDelete(path_in_repo="temp/new_file.md"),
                            CommitOperationAdd(
                                path_in_repo="buffer", path_or_fileobj=b"Buffer data"
                            ),
                            CommitOperationAdd(
                                path_in_repo="bytesio",
                                path_or_fileobj=BytesIO(b"BytesIO data"),
                            ),
                            CommitOperationAdd(
                                path_in_repo="fileobj", path_or_fileobj=fileobj
                            ),
                            CommitOperationAdd(
                                path_in_repo="nested/path",
                                path_or_fileobj=self.tmp_file,
                            ),
                        ]
                        resp = self._api.create_commit(
                            operations=operations,
                            commit_message="Test create_commit",
                            repo_id=f"{USER}/{REPO_NAME}",
                        )
                        # Check commit info
                        self.assertIsInstance(resp, CommitInfo)
                        self.assertIsNone(resp.pr_url)  # No pr created
                        self.assertIsNone(resp.pr_num)
                        self.assertIsNone(resp.pr_revision)
                    with self.assertRaises(HTTPError):
                        # Should raise a 404
                        hf_hub_download(
                            f"{USER}/{REPO_NAME}",
                            "temp/new_file.md",
                            use_auth_token=self._token,
                        )

                    for path, expected_content in [
                        ("buffer", b"Buffer data"),
                        ("bytesio", b"BytesIO data"),
                        ("fileobj", self.tmp_file_content.encode()),
                        ("nested/path", self.tmp_file_content.encode()),
                    ]:
                        filepath = hf_hub_download(
                            repo_id=f"{USER}/{REPO_NAME}",
                            filename=path,
                            revision="main",
                            use_auth_token=self._token,
                        )
                        self.assertTrue(filepath is not None)
                        with open(filepath, "rb") as downloaded_file:
                            content = downloaded_file.read()
                        self.assertEqual(content, expected_content)
                except Exception as err:
                    self.fail(err)
                finally:
                    self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_create_commit_conflict(self):
        REPO_NAME = repo_name("create_commit_conflict")
        self._api.create_repo(repo_id=REPO_NAME, exist_ok=False)
        parent_commit = self._api.model_info(f"{USER}/{REPO_NAME}").sha
        try:
            self._api.upload_file(
                path_or_fileobj=self.tmp_file,
                path_in_repo="temp/new_file.md",
                repo_id=f"{USER}/{REPO_NAME}",
            )
            operations = [
                CommitOperationAdd(
                    path_in_repo="buffer", path_or_fileobj=b"Buffer data"
                ),
            ]
            with self.assertRaises(HTTPError) as exc_ctx:
                self._api.create_commit(
                    operations=operations,
                    commit_message="Test create_commit",
                    repo_id=f"{USER}/{REPO_NAME}",
                    parent_commit=parent_commit,
                )
            self.assertEqual(exc_ctx.exception.response.status_code, 412)
            self.assertIn(
                # Check the server message is added to the exception
                "A commit has happened since. Please refresh and try again.",
                str(exc_ctx.exception),
            )
        except Exception as err:
            self.fail(err)
        finally:
            self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_create_commit_repo_does_not_exist(self) -> None:
        """Test error message is detailed when creating a commit on a missing repo."""
        # Test once with empty commit and once with an addition commit.
        for route, operations in (
            ("commit", []),
            ("preupload", [CommitOperationAdd("config.json", b"content")]),
        ):
            with self.subTest():
                with self.assertRaises(RepositoryNotFoundError) as context:
                    self._api.create_commit(
                        repo_id=f"{USER}/repo_that_do_not_exist",
                        operations=operations,
                        commit_message="fake_message",
                    )

                request_id = context.exception.response.headers.get("X-Request-Id")
                expected_message = (
                    f"404 Client Error. (Request ID: {request_id})\n\nRepository Not"
                    " Found for url:"
                    f" {self._api.endpoint}/api/models/{USER}/repo_that_do_not_exist/{route}/main.\nPlease"
                    " make sure you specified the correct `repo_id` and"
                    " `repo_type`.\nIf you are trying to access a private or gated"
                    " repo, make sure you are authenticated.\nNote: Creating a commit"
                    " assumes that the repo already exists on the Huggingface Hub."
                    " Please use `create_repo` if it's not the case."
                )

                self.assertEqual(str(context.exception), expected_message)

    @retry_endpoint
    def test_create_commit_lfs_file_implicit_token(self):
        """Test that uploading a file as LFS works with implicit token (from cache).

        Regression test for https://github.com/huggingface/huggingface_hub/pull/1084.
        """
        REPO_NAME = repo_name("create_commit_with_lfs")
        repo_id = f"{USER}/{REPO_NAME}"

        def _inner(mock: Mock) -> None:
            mock.return_value = self._token  # Set implicit token

            # Create repo
            self._api.create_repo(repo_id=REPO_NAME, exist_ok=False)

            # Set repo to track png files as LFS
            self._api.create_commit(
                operations=[
                    CommitOperationAdd(
                        path_in_repo=".gitattributes",
                        path_or_fileobj=b"*.png filter=lfs diff=lfs merge=lfs -text",
                    ),
                ],
                commit_message="Update .gitattributes",
                repo_id=repo_id,
            )

            # Upload a PNG file
            self._api.create_commit(
                operations=[
                    CommitOperationAdd(
                        path_in_repo="image.png", path_or_fileobj=b"image data"
                    ),
                ],
                commit_message="Test upload lfs file",
                repo_id=repo_id,
            )

            # Check uploaded as LFS
            info = self._api.model_info(
                repo_id=repo_id, use_auth_token=self._token, files_metadata=True
            )
            siblings = {file.rfilename: file for file in info.siblings}
            self.assertIsInstance(siblings["image.png"].lfs, dict)  # LFS file

            # Delete repo
            self._api.delete_repo(repo_id=REPO_NAME, token=self._token)

        with patch.object(self._api, "token", None):  # no default token
            with patch("huggingface_hub.utils.HfFolder.get_token") as mock:
                _inner(mock)  # just to avoid indenting twice the code code

    @retry_endpoint
    def test_create_commit_huge_regular_files(self):
        """Test committing 12 text files (>100MB in total) at once.

        This was not possible when using `json` format instead of `ndjson`
        on the `/create-commit` endpoint.

        See https://github.com/huggingface/huggingface_hub/pull/1117.
        """
        REPO_NAME = repo_name("create_commit_huge_regular_files")
        self._api.create_repo(repo_id=REPO_NAME, exist_ok=False)
        try:
            operations = []
            for num in range(12):
                operations.append(
                    CommitOperationAdd(
                        path_in_repo=f"file-{num}.text",
                        path_or_fileobj=b"Hello regular " + b"a" * 1024 * 1024 * 9,
                    )
                )
            self._api.create_commit(
                operations=operations,  # 12*9MB regular => too much for "old" method
                commit_message="Test create_commit with huge regular files",
                repo_id=f"{USER}/{REPO_NAME}",
            )
        except Exception as err:
            self.fail(err)
        finally:
            self._api.delete_repo(repo_id=REPO_NAME)

    @retry_endpoint
    def test_commit_preflight_on_lots_of_lfs_files(self):
        """Test committing 1300 LFS files at once.

        This was not possible when `fetch_upload_modes` was not fetching metadata by
        chunks. We are not testing the full upload as it would require to upload 1300
        files which is unnecessary for the test. Having an overall large payload (for
        `/create-commit` endpoint) is tested in `test_create_commit_huge_regular_files`.

        There is also a 25k LFS files limit on the Hub but this is not tested.

        See https://github.com/huggingface/huggingface_hub/pull/1117.
        """
        REPO_NAME = repo_name("commit_preflight_lots_of_lfs_files")
        self._api.create_repo(repo_id=REPO_NAME, exist_ok=False)
        try:
            operations = []
            for num in range(1300):
                operations.append(
                    CommitOperationAdd(
                        path_in_repo=f"file-{num}.bin",  # considered as LFS
                        path_or_fileobj=b"Hello LFS" + b"a" * 2048,  # big enough sample
                    )
                )

            # Test `fetch_upload_modes` preflight ("are they regular or LFS files?")
            res = fetch_upload_modes(
                additions=operations,
                repo_type="model",
                repo_id=f"{USER}/{REPO_NAME}",
                token=TOKEN,
                revision="main",
                endpoint=ENDPOINT_STAGING,
            )
            self.assertEqual(len(res), 1300)
            for _, mode in res.items():
                self.assertEqual(mode, "lfs")
        except Exception as err:
            self.fail(err)
        finally:
            self._api.delete_repo(repo_id=REPO_NAME)


class HfApiUploadEmptyFileTest(HfApiCommonTestWithLogin):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create repo for all tests as they are not dependent on each other.
        cls.repo_id = f"{USER}/{repo_name('upload_empty_file')}"
        cls._api.create_repo(repo_id=cls.repo_id, exist_ok=False)

    @classmethod
    def tearDownClass(cls):
        cls._api.delete_repo(repo_id=cls.repo_id)
        super().tearDownClass()

    def test_upload_empty_regular_file(self) -> None:
        with self.assertWarns(UserWarning):
            self._api.upload_file(
                repo_id=self.repo_id, path_in_repo="empty.txt", path_or_fileobj=b""
            )

    def test_upload_empty_gitkeep_file(self) -> None:
        # No warning in case of .gitkeep file
        with warnings.catch_warnings(record=True) as w:
            # Taken from https://stackoverflow.com/a/3892301
            self._api.upload_file(
                repo_id=self.repo_id, path_in_repo="foo/.gitkeep", path_or_fileobj=b""
            )
        self.assertEqual(len(w), 0)

    def test_upload_empty_lfs_file(self) -> None:
        # Should have been an LFS file, but uploaded as regular (would fail otherwise)
        with self.assertWarns(UserWarning):
            self._api.upload_file(
                repo_id=self.repo_id, path_in_repo="empty.pkl", path_or_fileobj=b""
            )
        info = self._api.repo_info(repo_id=self.repo_id, files_metadata=True)

        repo_file = {file.rfilename: file for file in info.siblings}["empty.pkl"]
        self.assertEqual(repo_file.size, 0)
        self.assertIsNone(repo_file.lfs)  # As regular


class HfApiDeleteFolderTest(HfApiCommonTestWithLogin):
    def setUp(self):
        self.repo_id = f"{USER}/{repo_name('create_commit_delete_folder')}"
        self._api.create_repo(repo_id=self.repo_id, exist_ok=False)

        self._api.create_commit(
            repo_id=self.repo_id,
            commit_message="Init repo",
            operations=[
                CommitOperationAdd(path_or_fileobj=b"data", path_in_repo="1/file_1.md"),
                CommitOperationAdd(path_or_fileobj=b"data", path_in_repo="1/file_2.md"),
                CommitOperationAdd(path_or_fileobj=b"data", path_in_repo="2/file_3.md"),
            ],
        )

    def tearDown(self):
        self._api.delete_repo(repo_id=self.repo_id)

    @retry_endpoint
    def test_create_commit_delete_folder_implicit(self):
        self._api.create_commit(
            operations=[CommitOperationDelete(path_in_repo="1/")],
            commit_message="Test delete folder implicit",
            repo_id=self.repo_id,
        )

        with self.assertRaises(EntryNotFoundError):
            hf_hub_download(self.repo_id, "1/file_1.md", use_auth_token=self._token)

        with self.assertRaises(EntryNotFoundError):
            hf_hub_download(self.repo_id, "1/file_2.md", use_auth_token=self._token)

        # Still exists
        hf_hub_download(self.repo_id, "2/file_3.md", use_auth_token=self._token)

    @retry_endpoint
    def test_create_commit_delete_folder_explicit(self):
        self._api.delete_folder(path_in_repo="1", repo_id=self.repo_id)
        with self.assertRaises(EntryNotFoundError):
            hf_hub_download(self.repo_id, "1/file_1.md", use_auth_token=self._token)

    @retry_endpoint
    def test_create_commit_failing_implicit_delete_folder(self):
        with self.assertRaisesRegex(
            EntryNotFoundError,
            "Make sure to differentiate file and folder paths",
        ):
            self._api.create_commit(
                operations=[CommitOperationDelete(path_in_repo="1")],
                commit_message="Failing delete folder",
                repo_id=self.repo_id,
            )


class HfApiTagEndpointTest(HfApiCommonTestWithLogin):
    @retry_endpoint
    @use_tmp_repo("model")
    def test_create_tag_on_main(self, repo_url: RepoUrl) -> None:
        """Check `create_tag` on default main branch works."""
        self._api.create_tag(
            repo_url.repo_id, tag="v0", tag_message="This is a tag message."
        )

        # Check tag  is on `main`
        tag_info = self._api.model_info(repo_url.repo_id, revision="v0")
        main_info = self._api.model_info(repo_url.repo_id, revision="main")
        self.assertEqual(tag_info.sha, main_info.sha)

    @retry_endpoint
    @use_tmp_repo("model")
    def test_create_tag_on_pr(self, repo_url: RepoUrl) -> None:
        """Check `create_tag` on a PR ref works."""
        # Create a PR with a readme
        commit_info: CommitInfo = self._api.create_commit(
            repo_id=repo_url.repo_id,
            create_pr=True,
            commit_message="upload readme",
            operations=[
                CommitOperationAdd(
                    path_or_fileobj=b"this is a file content", path_in_repo="readme.md"
                )
            ],
        )

        # Tag the PR
        self._api.create_tag(
            repo_url.repo_id, tag="v0", revision=commit_info.pr_revision
        )

        # Check tag  is on `refs/pr/1`
        tag_info = self._api.model_info(repo_url.repo_id, revision="v0")
        pr_info = self._api.model_info(
            repo_url.repo_id, revision=commit_info.pr_revision
        )
        main_info = self._api.model_info(repo_url.repo_id)

        self.assertEqual(tag_info.sha, pr_info.sha)
        self.assertNotEqual(tag_info.sha, main_info.sha)

    @retry_endpoint
    @use_tmp_repo("dataset")
    def test_create_tag_on_commit_oid(self, repo_url: RepoUrl) -> None:
        """Check `create_tag` on specific commit oid works (both long and shorthands).

        Test it on a `dataset` repo.
        """
        # Create a PR with a readme
        commit_info_1: CommitInfo = self._api.create_commit(
            repo_id=repo_url.repo_id,
            repo_type="dataset",
            commit_message="upload readme",
            operations=[
                CommitOperationAdd(
                    path_or_fileobj=b"this is a file content", path_in_repo="readme.md"
                )
            ],
        )
        commit_info_2: CommitInfo = self._api.create_commit(
            repo_id=repo_url.repo_id,
            repo_type="dataset",
            commit_message="upload config",
            operations=[
                CommitOperationAdd(
                    path_or_fileobj=b"{'hello': 'world'}", path_in_repo="config.json"
                )
            ],
        )

        # Tag commits
        self._api.create_tag(
            repo_url.repo_id,
            tag="commit_1",
            repo_type="dataset",
            revision=commit_info_1.oid,  # long version
        )
        self._api.create_tag(
            repo_url.repo_id,
            tag="commit_2",
            repo_type="dataset",
            revision=commit_info_2.oid[:7],  # use shorthand !
        )

        # Check tags
        tag_1_info = self._api.dataset_info(repo_url.repo_id, revision="commit_1")
        tag_2_info = self._api.dataset_info(repo_url.repo_id, revision="commit_2")

        self.assertEqual(tag_1_info.sha, commit_info_1.oid)
        self.assertEqual(tag_2_info.sha, commit_info_2.oid)

    @retry_endpoint
    @use_tmp_repo("model")
    def test_invalid_tag_name(self, repo_url: RepoUrl) -> None:
        """Check `create_tag` with an invalid tag name."""
        with self.assertRaises(HTTPError):
            self._api.create_tag(repo_url.repo_id, tag="invalid tag")

    @retry_endpoint
    @use_tmp_repo("model")
    def test_create_tag_on_missing_revision(self, repo_url: RepoUrl) -> None:
        """Check `create_tag` on a missing revision."""
        with self.assertRaises(RevisionNotFoundError):
            self._api.create_tag(repo_url.repo_id, tag="invalid tag", revision="foobar")

    @retry_endpoint
    @use_tmp_repo("model")
    def test_create_tag_twice(self, repo_url: RepoUrl) -> None:
        """Check `create_tag` called twice on same tag should fail with HTTP 409."""
        self._api.create_tag(repo_url.repo_id, tag="tag_1")
        with self.assertRaises(HfHubHTTPError) as err:
            self._api.create_tag(repo_url.repo_id, tag="tag_1")
        self.assertEqual(err.exception.response.status_code, 409)

        # exist_ok=True => doesn't fail
        self._api.create_tag(repo_url.repo_id, tag="tag_1", exist_ok=True)

    @retry_endpoint
    @use_tmp_repo("model")
    def test_create_and_delete_tag(self, repo_url: RepoUrl) -> None:
        """Check `delete_tag` deletes the tag."""
        self._api.create_tag(repo_url.repo_id, tag="v0")
        self._api.model_info(repo_url.repo_id, revision="v0")

        self._api.delete_tag(repo_url.repo_id, tag="v0")
        with self.assertRaises(RevisionNotFoundError):
            self._api.model_info(repo_url.repo_id, revision="v0")

    @retry_endpoint
    @use_tmp_repo("model")
    def test_delete_tag_missing_tag(self, repo_url: RepoUrl) -> None:
        """Check cannot `delete_tag` if tag doesn't exist."""
        with self.assertRaises(RevisionNotFoundError):
            self._api.delete_tag(repo_url.repo_id, tag="v0")

    @retry_endpoint
    @use_tmp_repo("model")
    def test_delete_tag_with_branch_name(self, repo_url: RepoUrl) -> None:
        """Try to `delete_tag` if tag is a branch name.

        Currently getting a HTTP 500.
        See https://github.com/huggingface/moon-landing/issues/4223.
        """
        with self.assertRaises(HfHubHTTPError):
            self._api.delete_tag(repo_url.repo_id, tag="main")


class HfApiBranchEndpointTest(HfApiCommonTestWithLogin):
    @retry_endpoint
    @use_tmp_repo()
    def test_create_and_delete_branch(self, repo_url: RepoUrl) -> None:
        """Test `create_branch` from main branch."""
        self._api.create_branch(repo_url.repo_id, branch="cool-branch")

        # Check `cool-branch` branch exists
        self._api.model_info(repo_url.repo_id, revision="cool-branch")

        # Delete it
        self._api.delete_branch(repo_url.repo_id, branch="cool-branch")

        # Check doesn't exist anymore
        with self.assertRaises(RevisionNotFoundError):
            self._api.model_info(repo_url.repo_id, revision="cool-branch")

    @retry_endpoint
    @use_tmp_repo()
    def test_create_branch_existing_branch_fails(self, repo_url: RepoUrl) -> None:
        """Test `create_branch` on existing branch."""
        self._api.create_branch(repo_url.repo_id, branch="cool-branch")

        with self.assertRaisesRegex(HfHubHTTPError, "Reference already exists"):
            self._api.create_branch(repo_url.repo_id, branch="cool-branch")

        with self.assertRaisesRegex(HfHubHTTPError, "Reference already exists"):
            self._api.create_branch(repo_url.repo_id, branch="main")

        # exist_ok=True => doesn't fail
        self._api.create_branch(repo_url.repo_id, branch="cool-branch", exist_ok=True)
        self._api.create_branch(repo_url.repo_id, branch="main", exist_ok=True)

    @retry_endpoint
    @use_tmp_repo()
    def test_create_branch_existing_tag_does_not_fail(self, repo_url: RepoUrl) -> None:
        """Test `create_branch` on existing tag."""
        self._api.create_tag(repo_url.repo_id, tag="tag")
        self._api.create_branch(repo_url.repo_id, branch="tag")

    @retry_endpoint
    @use_tmp_repo()
    def test_create_branch_forbidden_ref_branch_fails(self, repo_url: RepoUrl) -> None:
        """Test `create_branch` on forbidden ref branch."""
        with self.assertRaisesRegex(BadRequestError, "Invalid reference for a branch"):
            self._api.create_branch(repo_url.repo_id, branch="refs/pr/5")

        with self.assertRaisesRegex(BadRequestError, "Invalid reference for a branch"):
            self._api.create_branch(repo_url.repo_id, branch="refs/something/random")

    @retry_endpoint
    @use_tmp_repo()
    def test_delete_branch_on_protected_branch_fails(self, repo_url: RepoUrl) -> None:
        """Test `delete_branch` fails on protected branch."""
        with self.assertRaisesRegex(HfHubHTTPError, "Cannot delete refs/heads/main"):
            self._api.delete_branch(repo_url.repo_id, branch="main")

    @retry_endpoint
    @use_tmp_repo()
    def test_delete_branch_on_missing_branch_fails(self, repo_url: RepoUrl) -> None:
        """Test `delete_branch` fails on missing branch."""
        with self.assertRaisesRegex(HfHubHTTPError, "Reference does not exist"):
            self._api.delete_branch(repo_url.repo_id, branch="cool-branch")

        # Using a tag instead of branch -> fails
        self._api.create_tag(repo_url.repo_id, tag="cool-tag")
        with self.assertRaisesRegex(HfHubHTTPError, "Reference does not exist"):
            self._api.delete_branch(repo_url.repo_id, branch="cool-tag")


class HfApiPublicStagingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._api = HfApi()

    def test_staging_list_datasets(self):
        self._api.list_datasets()

    def test_staging_list_models(self):
        self._api.list_models()

    def test_staging_list_metrics(self):
        self._api.list_metrics()


class HfApiPublicProductionTest(unittest.TestCase):
    @with_production_testing
    def setUp(self) -> None:
        self._api = HfApi()

    @expect_deprecation("list_models")
    def test_list_models(self):
        models = self._api.list_models()
        self.assertGreater(len(models), 100)
        self.assertIsInstance(models[0], ModelInfo)

    @expect_deprecation("list_models")
    def test_list_models_author(self):
        models = self._api.list_models(author="google")
        self.assertGreater(len(models), 10)
        self.assertIsInstance(models[0], ModelInfo)
        for model in models:
            self.assertTrue(model.modelId.startswith("google/"))

    @expect_deprecation("list_models")
    def test_list_models_search(self):
        models = self._api.list_models(search="bert")
        self.assertGreater(len(models), 10)
        self.assertIsInstance(models[0], ModelInfo)
        for model in models[:10]:
            # Rough rule: at least first 10 will have "bert" in the name
            # Not optimal since it is dependent on how the Hub implements the search
            # (and changes it in the future) but for now it should do the trick.
            self.assertTrue("bert" in model.modelId.lower())

    @expect_deprecation("list_models")
    def test_list_models_complex_query(self):
        # Let's list the 10 most recent models
        # with tags "bert" and "jax",
        # ordered by last modified date.
        models = self._api.list_models(
            filter=("bert", "jax"), sort="lastModified", direction=-1, limit=10
        )
        # we have at least 1 models
        self.assertGreater(len(models), 1)
        self.assertLessEqual(len(models), 10)
        model = models[0]
        self.assertIsInstance(model, ModelInfo)
        self.assertTrue(all(tag in model.tags for tag in ["bert", "jax"]))

    def test_list_models_with_config(self):
        for model in self._api.list_models(
            filter="adapter-transformers", fetch_config=True, limit=20
        ):
            self.assertIsNotNone(model.config)

    def test_list_models_without_config(self):
        for model in self._api.list_models(
            filter="adapter-transformers", fetch_config=False, limit=20
        ):
            self.assertIsNone(model.config)

    def test_model_info(self):
        model = self._api.model_info(repo_id=DUMMY_MODEL_ID)
        self.assertIsInstance(model, ModelInfo)
        self.assertNotEqual(model.sha, DUMMY_MODEL_ID_REVISION_ONE_SPECIFIC_COMMIT)
        # One particular commit (not the top of `main`)
        model = self._api.model_info(
            repo_id=DUMMY_MODEL_ID, revision=DUMMY_MODEL_ID_REVISION_ONE_SPECIFIC_COMMIT
        )
        self.assertIsInstance(model, ModelInfo)
        self.assertEqual(model.sha, DUMMY_MODEL_ID_REVISION_ONE_SPECIFIC_COMMIT)

    # TODO; un-skip this test once it's fixed.
    @unittest.skip(
        "Security status is currently unreliable on the server endpoint, so this"
        " test occasionally fails. Issue is tracked in"
        " https://github.com/huggingface/huggingface_hub/issues/1002 and"
        " https://github.com/huggingface/moon-landing/issues/3695. TODO: un-skip"
        " this test once it's fixed."
    )
    def test_model_info_with_security(self):
        model = self._api.model_info(
            repo_id=DUMMY_MODEL_ID,
            revision=DUMMY_MODEL_ID_REVISION_ONE_SPECIFIC_COMMIT,
            securityStatus=True,
        )
        self.assertEqual(model.securityStatus, {"containsInfected": False})

    def test_model_info_with_file_metadata(self):
        model = self._api.model_info(
            repo_id=DUMMY_MODEL_ID,
            revision=DUMMY_MODEL_ID_REVISION_ONE_SPECIFIC_COMMIT,
            files_metadata=True,
        )
        files = model.siblings
        assert files is not None
        self._check_siblings_metadata(files)

    def test_list_repo_files(self):
        files = self._api.list_repo_files(repo_id=DUMMY_MODEL_ID)
        expected_files = [
            ".gitattributes",
            "README.md",
            "config.json",
            "flax_model.msgpack",
            "merges.txt",
            "pytorch_model.bin",
            "tf_model.h5",
            "vocab.json",
        ]
        self.assertListEqual(files, expected_files)

    @expect_deprecation("list_datasets")
    def test_list_datasets_no_filter(self):
        datasets = self._api.list_datasets()
        self.assertGreater(len(datasets), 100)
        self.assertIsInstance(datasets[0], DatasetInfo)

    @expect_deprecation("list_datasets")
    def test_filter_datasets_by_author_and_name(self):
        f = DatasetFilter(author="huggingface", dataset_name="DataMeasurementsFiles")
        datasets = self._api.list_datasets(filter=f)
        self.assertEqual(len(datasets), 1)
        self.assertTrue("huggingface" in datasets[0].author)
        self.assertTrue("DataMeasurementsFiles" in datasets[0].id)

    @unittest.skip(
        "DatasetFilter is currently broken. See"
        " https://github.com/huggingface/huggingface_hub/pull/1250. Skip test until"
        " it's fixed."
    )
    @expect_deprecation("list_datasets")
    def test_filter_datasets_by_benchmark(self):
        f = DatasetFilter(benchmark="raft")
        datasets = self._api.list_datasets(filter=f)
        self.assertGreater(len(datasets), 0)
        self.assertTrue("benchmark:raft" in datasets[0].tags)

    @expect_deprecation("list_datasets")
    def test_filter_datasets_by_language_creator(self):
        f = DatasetFilter(language_creators="crowdsourced")
        datasets = self._api.list_datasets(filter=f)
        self.assertGreater(len(datasets), 0)
        self.assertTrue("language_creators:crowdsourced" in datasets[0].tags)

    @unittest.skip(
        "DatasetFilter is currently broken. See"
        " https://github.com/huggingface/huggingface_hub/pull/1250. Skip test until"
        " it's fixed."
    )
    @expect_deprecation("list_datasets")
    def test_filter_datasets_by_language_only(self):
        datasets = self._api.list_datasets(filter=DatasetFilter(language="en"))
        self.assertGreater(len(datasets), 0)
        self.assertTrue("language:en" in datasets[0].tags)

        args = DatasetSearchArguments(api=self._api)
        datasets = self._api.list_datasets(
            filter=DatasetFilter(language=(args.language.en, args.language.fr))
        )
        self.assertGreater(len(datasets), 0)
        self.assertTrue("language:en" in datasets[0].tags)
        self.assertTrue("language:fr" in datasets[0].tags)

    @expect_deprecation("list_datasets")
    def test_filter_datasets_by_multilinguality(self):
        datasets = self._api.list_datasets(
            filter=DatasetFilter(multilinguality="multilingual")
        )
        self.assertGreater(len(datasets), 0)
        self.assertTrue("multilinguality:multilingual" in datasets[0].tags)

    @expect_deprecation("list_datasets")
    def test_filter_datasets_by_size_categories(self):
        datasets = self._api.list_datasets(
            filter=DatasetFilter(size_categories="100K<n<1M")
        )
        self.assertGreater(len(datasets), 0)
        self.assertTrue("size_categories:100K<n<1M" in datasets[0].tags)

    @expect_deprecation("list_datasets")
    def test_filter_datasets_by_task_categories(self):
        datasets = self._api.list_datasets(
            filter=DatasetFilter(task_categories="audio-classification")
        )
        self.assertGreater(len(datasets), 0)
        self.assertTrue("task_categories:audio-classification" in datasets[0].tags)

    @expect_deprecation("list_datasets")
    def test_filter_datasets_by_task_ids(self):
        datasets = self._api.list_datasets(
            filter=DatasetFilter(task_ids="natural-language-inference")
        )
        self.assertGreater(len(datasets), 0)
        self.assertTrue("task_ids:natural-language-inference" in datasets[0].tags)

    @expect_deprecation("list_datasets")
    def test_list_datasets_full(self):
        datasets = self._api.list_datasets(full=True)
        self.assertGreater(len(datasets), 100)
        dataset = datasets[0]
        self.assertIsInstance(dataset, DatasetInfo)
        self.assertTrue(any(dataset.cardData for dataset in datasets))

    @expect_deprecation("list_datasets")
    def test_list_datasets_author(self):
        datasets = self._api.list_datasets(author="huggingface")
        self.assertGreater(len(datasets), 1)
        self.assertIsInstance(datasets[0], DatasetInfo)

    @expect_deprecation("list_datasets")
    def test_list_datasets_search(self):
        datasets = self._api.list_datasets(search="wikipedia")
        self.assertGreater(len(datasets), 10)
        self.assertIsInstance(datasets[0], DatasetInfo)

    @expect_deprecation("list_datasets")
    def test_filter_datasets_with_cardData(self):
        datasets = self._api.list_datasets(cardData=True)
        self.assertGreater(
            sum(
                [getattr(dataset, "cardData", None) is not None for dataset in datasets]
            ),
            0,
        )
        datasets = self._api.list_datasets()
        self.assertTrue(
            all([getattr(dataset, "cardData", None) is None for dataset in datasets])
        )

    def test_dataset_info(self):
        dataset = self._api.dataset_info(repo_id=DUMMY_DATASET_ID)
        self.assertTrue(
            isinstance(dataset.cardData, dict) and len(dataset.cardData) > 0
        )
        self.assertTrue(
            isinstance(dataset.siblings, list) and len(dataset.siblings) > 0
        )
        self.assertIsInstance(dataset, DatasetInfo)
        self.assertNotEqual(dataset.sha, DUMMY_DATASET_ID_REVISION_ONE_SPECIFIC_COMMIT)
        dataset = self._api.dataset_info(
            repo_id=DUMMY_DATASET_ID,
            revision=DUMMY_DATASET_ID_REVISION_ONE_SPECIFIC_COMMIT,
        )
        self.assertIsInstance(dataset, DatasetInfo)
        self.assertEqual(dataset.sha, DUMMY_DATASET_ID_REVISION_ONE_SPECIFIC_COMMIT)

    def test_dataset_info_with_file_metadata(self):
        dataset = self._api.dataset_info(
            repo_id=SAMPLE_DATASET_IDENTIFIER,
            files_metadata=True,
        )
        files = dataset.siblings
        assert files is not None
        self._check_siblings_metadata(files)

    def _check_siblings_metadata(self, files: List[RepoFile]):
        """Check requested metadata has been received from the server."""
        at_least_one_lfs = False
        for file in files:
            self.assertTrue(isinstance(file.blob_id, str))
            self.assertTrue(isinstance(file.size, int))
            if file.lfs is not None:
                at_least_one_lfs = True
                self.assertTrue(isinstance(file.lfs, dict))
                self.assertTrue("sha256" in file.lfs)
        self.assertTrue(at_least_one_lfs)

    def test_list_metrics(self):
        metrics = self._api.list_metrics()
        self.assertGreater(len(metrics), 10)
        self.assertIsInstance(metrics[0], MetricInfo)
        self.assertTrue(any(metric.description for metric in metrics))

    @expect_deprecation("list_models")
    def test_filter_models_by_author(self):
        models = self._api.list_models(filter=ModelFilter(author="muellerzr"))
        self.assertGreater(len(models), 0)
        self.assertTrue("muellerzr" in models[0].modelId)

    @expect_deprecation("list_models")
    def test_filter_models_by_author_and_name(self):
        # Test we can search by an author and a name, but the model is not found
        models = self._api.list_models(
            filter=ModelFilter("facebook", model_name="bart-base")
        )
        self.assertTrue("facebook/bart-base" in models[0].modelId)

    @expect_deprecation("list_models")
    def test_failing_filter_models_by_author_and_model_name(self):
        # Test we can search by an author and a name, but the model is not found
        models = self._api.list_models(
            filter=ModelFilter(author="muellerzr", model_name="testme")
        )
        self.assertEqual(len(models), 0)

    @expect_deprecation("list_models")
    def test_filter_models_with_library(self):
        models = self._api.list_models(
            filter=ModelFilter(
                "microsoft", model_name="wavlm-base-sd", library="tensorflow"
            )
        )
        self.assertEqual(len(models), 0)

        models = self._api.list_models(
            filter=ModelFilter(
                "microsoft", model_name="wavlm-base-sd", library="pytorch"
            )
        )
        self.assertGreater(len(models), 0)

    @expect_deprecation("list_models")
    def test_filter_models_with_task(self):
        models = self._api.list_models(
            filter=ModelFilter(task="fill-mask", model_name="albert-base-v2")
        )
        self.assertTrue("fill-mask" == models[0].pipeline_tag)
        self.assertTrue("albert-base-v2" in models[0].modelId)

        models = self._api.list_models(filter=ModelFilter(task="dummytask"))
        self.assertEqual(len(models), 0)

    @expect_deprecation("list_models")
    def test_filter_models_by_language(self):
        res_fr = self._api.list_models(filter=ModelFilter(language="fr"))
        res_en = self._api.list_models(filter=ModelFilter(language="en"))
        self.assertGreater(len(res_en), len(res_fr))

    @expect_deprecation("list_models")
    def test_filter_models_with_complex_query(self):
        args = ModelSearchArguments(api=self._api)
        f = ModelFilter(
            task=args.pipeline_tag.TextClassification,
            library=[args.library.PyTorch, args.library.TensorFlow],
        )
        models = self._api.list_models(filter=f)
        self.assertGreater(len(models), 1)
        self.assertTrue(
            [
                "text-classification" in model.pipeline_tag
                or "text-classification" in model.tags
                for model in models
            ]
        )
        self.assertTrue(
            ["pytorch" in model.tags and "tf" in model.tags for model in models]
        )

    def test_filter_models_with_cardData(self):
        models = self._api.list_models(filter="co2_eq_emissions", cardData=True)
        self.assertTrue([hasattr(model, "cardData") for model in models])
        models = self._api.list_models(filter="co2_eq_emissions")
        self.assertTrue(all([not hasattr(model, "cardData") for model in models]))

    def test_filter_emissions_dict(self):
        # tests that dictionary is handled correctly as "emissions" and that
        # 17g is accepted and parsed correctly as a value
        # regression test for #753
        model = ModelInfo(cardData={"co2_eq_emissions": {"emissions": "17g"}})
        res = _filter_emissions([model], -1, 100)
        assert len(res) == 1

    def test_filter_emissions_with_max(self):
        models = self._api.list_models(emissions_thresholds=(None, 100), cardData=True)
        self.assertTrue(
            all(
                [
                    model.cardData["co2_eq_emissions"] <= 100
                    for model in models
                    if isinstance(model.cardData["co2_eq_emissions"], (float, int))
                ]
            )
        )

    def test_filter_emissions_with_min(self):
        models = self._api.list_models(emissions_thresholds=(5, None), cardData=True)
        self.assertTrue(
            all(
                [
                    model.cardData["co2_eq_emissions"] >= 5
                    for model in models
                    if isinstance(model.cardData["co2_eq_emissions"], (float, int))
                ]
            )
        )

    def test_filter_emissions_with_min_and_max(self):
        models = self._api.list_models(emissions_thresholds=(5, 100), cardData=True)
        self.assertTrue(
            all(
                [
                    model.cardData["co2_eq_emissions"] >= 5
                    for model in models
                    if isinstance(model.cardData["co2_eq_emissions"], (float, int))
                ]
            )
        )
        self.assertTrue(
            all(
                [
                    model.cardData["co2_eq_emissions"] <= 100
                    for model in models
                    if isinstance(model.cardData["co2_eq_emissions"], (float, int))
                ]
            )
        )

    @expect_deprecation("list_spaces")
    def test_list_spaces_full(self):
        spaces = self._api.list_spaces(full=True)
        self.assertGreater(len(spaces), 100)
        space = spaces[0]
        self.assertIsInstance(space, SpaceInfo)
        self.assertTrue(any(space.cardData for space in spaces))

    @expect_deprecation("list_spaces")
    def test_list_spaces_author(self):
        spaces = self._api.list_spaces(author="evaluate-metric")
        self.assertGreater(len(spaces), 10)
        self.assertTrue(
            set([space.id for space in spaces]).issuperset(
                set(["evaluate-metric/trec_eval", "evaluate-metric/perplexity"])
            )
        )

    @expect_deprecation("list_spaces")
    def test_list_spaces_search(self):
        spaces = self._api.list_spaces(search="wikipedia")
        space = spaces[0]
        self.assertTrue("wikipedia" in space.id.lower())

    @expect_deprecation("list_spaces")
    def test_list_spaces_sort_and_direction(self):
        spaces_descending_likes = self._api.list_spaces(sort="likes", direction=-1)
        spaces_ascending_likes = self._api.list_spaces(sort="likes")
        self.assertGreater(
            spaces_descending_likes[0].likes, spaces_descending_likes[1].likes
        )
        self.assertLess(
            spaces_ascending_likes[-2].likes, spaces_ascending_likes[-1].likes
        )

    @expect_deprecation("list_spaces")
    def test_list_spaces_limit(self):
        spaces = self._api.list_spaces(limit=5)
        self.assertEqual(len(spaces), 5)

    @expect_deprecation("list_spaces")
    def test_list_spaces_with_models(self):
        spaces = self._api.list_spaces(models="bert-base-uncased")
        self.assertTrue("bert-base-uncased" in getattr(spaces[0], "models", []))

    @expect_deprecation("list_spaces")
    def test_list_spaces_with_datasets(self):
        spaces = self._api.list_spaces(datasets="wikipedia")
        self.assertTrue("wikipedia" in getattr(spaces[0], "datasets", []))

    def test_list_spaces_linked(self):
        spaces = self._api.list_spaces(linked=True)
        self.assertTrue(
            any((getattr(space, "models", None) is not None) for space in spaces)
        )
        self.assertTrue(
            any((getattr(space, "datasets", None) is not None) for space in spaces)
        )
        self.assertTrue(
            any(
                (getattr(space, "models", None) is not None)
                and getattr(space, "datasets", None) is not None
            )
            for space in spaces
        )
        self.assertTrue(
            all(
                (getattr(space, "models", None) is not None)
                or getattr(space, "datasets", None) is not None
            )
            for space in spaces
        )


class HfApiPrivateTest(HfApiCommonTestWithLogin):
    @retry_endpoint
    def setUp(self) -> None:
        super().setUp()
        self.REPO_NAME = repo_name("private")
        self._api.create_repo(repo_id=self.REPO_NAME, private=True)
        self._api.create_repo(repo_id=self.REPO_NAME, private=True, repo_type="dataset")

    def tearDown(self) -> None:
        self._api.delete_repo(repo_id=self.REPO_NAME)
        self._api.delete_repo(repo_id=self.REPO_NAME, repo_type="dataset")

    def test_model_info(self):
        shutil.rmtree(os.path.dirname(HfFolder.path_token), ignore_errors=True)
        with patch.object(self._api, "token", None):  # no default token
            # Test we cannot access model info without a token
            with self.assertRaisesRegex(
                requests.exceptions.HTTPError,
                re.compile(
                    r"401 Client Error(.+)\(Request ID: .+\)(.*)Repository Not Found",
                    flags=re.DOTALL,
                ),
            ):
                _ = self._api.model_info(repo_id=f"{USER}/{self.REPO_NAME}")

            model_info = self._api.model_info(
                repo_id=f"{USER}/{self.REPO_NAME}", use_auth_token=self._token
            )
            self.assertIsInstance(model_info, ModelInfo)

    def test_dataset_info(self):
        shutil.rmtree(os.path.dirname(HfFolder.path_token), ignore_errors=True)
        with patch.object(self._api, "token", None):  # no default token
            # Test we cannot access model info without a token
            with self.assertRaisesRegex(
                requests.exceptions.HTTPError,
                re.compile(
                    r"401 Client Error(.+)\(Request ID: .+\)(.*)Repository Not Found",
                    flags=re.DOTALL,
                ),
            ):
                _ = self._api.dataset_info(repo_id=f"{USER}/{self.REPO_NAME}")

            dataset_info = self._api.dataset_info(
                repo_id=f"{USER}/{self.REPO_NAME}", use_auth_token=self._token
            )
            self.assertIsInstance(dataset_info, DatasetInfo)

    @expect_deprecation("list_datasets")
    def test_list_private_datasets(self):
        orig = len(self._api.list_datasets(use_auth_token=False))
        new = len(self._api.list_datasets(use_auth_token=self._token))
        self.assertGreater(new, orig)

    @expect_deprecation("list_models")
    def test_list_private_models(self):
        orig = len(self._api.list_models(use_auth_token=False))
        new = len(self._api.list_models(use_auth_token=self._token))
        self.assertGreater(new, orig)

    @expect_deprecation("list_spaces")
    @with_production_testing
    def test_list_private_spaces(self):
        orig = len(self._api.list_spaces(use_auth_token=False))
        new = len(self._api.list_spaces(use_auth_token=self._token))
        self.assertGreaterEqual(new, orig)


@require_git_lfs
class HfLargefilesTest(HfApiCommonTest):
    @classmethod
    @expect_deprecation("set_access_token")
    def setUpClass(cls):
        """
        Share this valid token in all tests below.
        """
        cls._token = TOKEN
        cls._api.token = TOKEN
        cls._api.set_access_token(TOKEN)

    def setUp(self):
        self.REPO_NAME_LARGE_FILE = large_file_repo_name()
        if os.path.exists(WORKING_REPO_DIR):
            rmtree_with_retry(WORKING_REPO_DIR)
        logger.info(
            f"Does {WORKING_REPO_DIR} exist: {os.path.exists(WORKING_REPO_DIR)}"
        )

    def tearDown(self):
        self._api.delete_repo(repo_id=self.REPO_NAME_LARGE_FILE)

    def setup_local_clone(self, REMOTE_URL):
        REMOTE_URL_AUTH = REMOTE_URL.replace(
            ENDPOINT_STAGING, ENDPOINT_STAGING_BASIC_AUTH
        )
        subprocess.run(
            ["git", "clone", REMOTE_URL_AUTH, WORKING_REPO_DIR],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "lfs", "track", "*.pdf"], check=True, cwd=WORKING_REPO_DIR
        )
        subprocess.run(
            ["git", "lfs", "track", "*.epub"], check=True, cwd=WORKING_REPO_DIR
        )

    @retry_endpoint
    def test_end_to_end_thresh_6M(self):
        self._api._lfsmultipartthresh = 6 * 10**6
        REMOTE_URL = self._api.create_repo(repo_id=self.REPO_NAME_LARGE_FILE)
        self._api._lfsmultipartthresh = None
        self.setup_local_clone(REMOTE_URL)

        subprocess.run(
            ["wget", LARGE_FILE_18MB],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=WORKING_REPO_DIR,
        )
        subprocess.run(["git", "add", "*"], check=True, cwd=WORKING_REPO_DIR)
        subprocess.run(
            ["git", "commit", "-m", "commit message"], check=True, cwd=WORKING_REPO_DIR
        )

        # This will fail as we haven't set up our custom transfer agent yet.
        failed_process = subprocess.run(
            ["git", "push"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=WORKING_REPO_DIR,
        )
        self.assertEqual(failed_process.returncode, 1)
        self.assertIn("cli lfs-enable-largefiles", failed_process.stderr.decode())
        # ^ Instructions on how to fix this are included in the error message.

        subprocess.run(
            ["huggingface-cli", "lfs-enable-largefiles", WORKING_REPO_DIR], check=True
        )

        start_time = time.time()
        subprocess.run(["git", "push"], check=True, cwd=WORKING_REPO_DIR)
        print("took", time.time() - start_time)

        # To be 100% sure, let's download the resolved file
        pdf_url = f"{REMOTE_URL}/resolve/main/progit.pdf"
        DEST_FILENAME = "uploaded.pdf"
        subprocess.run(
            ["wget", pdf_url, "-O", DEST_FILENAME],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=WORKING_REPO_DIR,
        )
        dest_filesize = os.stat(os.path.join(WORKING_REPO_DIR, DEST_FILENAME)).st_size
        self.assertEqual(dest_filesize, 18685041)

    @retry_endpoint
    def test_end_to_end_thresh_16M(self):
        # Here we'll push one multipart and one non-multipart file in the same commit, and see what happens
        self._api._lfsmultipartthresh = 16 * 10**6
        REMOTE_URL = self._api.create_repo(repo_id=self.REPO_NAME_LARGE_FILE)
        self._api._lfsmultipartthresh = None
        self.setup_local_clone(REMOTE_URL)

        subprocess.run(
            ["wget", LARGE_FILE_18MB],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=WORKING_REPO_DIR,
        )
        subprocess.run(
            ["wget", LARGE_FILE_14MB],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=WORKING_REPO_DIR,
        )
        subprocess.run(["git", "add", "*"], check=True, cwd=WORKING_REPO_DIR)
        subprocess.run(
            ["git", "commit", "-m", "both files in same commit"],
            check=True,
            cwd=WORKING_REPO_DIR,
        )

        subprocess.run(
            ["huggingface-cli", "lfs-enable-largefiles", WORKING_REPO_DIR], check=True
        )

        start_time = time.time()
        subprocess.run(["git", "push"], check=True, cwd=WORKING_REPO_DIR)
        print("took", time.time() - start_time)


class HfApiMiscTest(unittest.TestCase):
    def test_repo_type_and_id_from_hf_id(self):
        possible_values = {
            "https://huggingface.co/id": [None, None, "id"],
            "https://huggingface.co/user/id": [None, "user", "id"],
            "https://huggingface.co/datasets/user/id": ["dataset", "user", "id"],
            "https://huggingface.co/spaces/user/id": ["space", "user", "id"],
            "user/id": [None, "user", "id"],
            "dataset/user/id": ["dataset", "user", "id"],
            "space/user/id": ["space", "user", "id"],
            "id": [None, None, "id"],
        }

        for key, value in possible_values.items():
            self.assertEqual(
                repo_type_and_id_from_hf_id(key, hub_url="https://huggingface.co"),
                tuple(value),
            )


class HfApiDiscussionsTest(HfApiCommonTestWithLogin):
    def setUp(self):
        super().setUp()
        self.repo_name = f"{USER}/{repo_name()}"
        self._api.create_repo(repo_id=self.repo_name)
        self.pull_request = self._api.create_discussion(
            repo_id=self.repo_name, pull_request=True, title="Test Pull Request"
        )
        self.discussion = self._api.create_discussion(
            repo_id=self.repo_name, pull_request=False, title="Test Discussion"
        )

    def tearDown(self):
        self._api.delete_repo(repo_id=self.repo_name)
        super().tearDown()

    def test_create_discussion(self):
        discussion = self._api.create_discussion(
            repo_id=self.repo_name, title=" Test discussion !  "
        )
        self.assertEqual(discussion.num, 3)
        self.assertEqual(discussion.author, USER)
        self.assertEqual(discussion.is_pull_request, False)
        self.assertEqual(discussion.title, "Test discussion !")

    def test_create_pull_request(self):
        discussion = self._api.create_discussion(
            repo_id=self.repo_name, title=" Test PR !  ", pull_request=True
        )
        self.assertEqual(discussion.num, 3)
        self.assertEqual(discussion.author, USER)
        self.assertEqual(discussion.is_pull_request, True)
        self.assertEqual(discussion.title, "Test PR !")

        model_info = self._api.repo_info(
            repo_id=self.repo_name,
            revision="refs/pr/1",
        )
        self.assertIsInstance(model_info, ModelInfo)

    def test_get_repo_discussion(self):
        discussions_generator = self._api.get_repo_discussions(repo_id=self.repo_name)
        self.assertIsInstance(discussions_generator, types.GeneratorType)
        self.assertListEqual(
            list([d.num for d in discussions_generator]),
            [self.discussion.num, self.pull_request.num],
        )

    def test_get_discussion_details(self):
        retrieved = self._api.get_discussion_details(
            repo_id=self.repo_name, discussion_num=2
        )
        self.assertEqual(retrieved, self.discussion)

    def test_edit_discussion_comment(self):
        def get_first_comment(discussion: DiscussionWithDetails) -> DiscussionComment:
            return [evt for evt in discussion.events if evt.type == "comment"][0]

        edited_comment = self._api.edit_discussion_comment(
            repo_id=self.repo_name,
            discussion_num=self.pull_request.num,
            comment_id=get_first_comment(self.pull_request).id,
            new_content="**Edited** comment 🤗",
        )
        retrieved = self._api.get_discussion_details(
            repo_id=self.repo_name, discussion_num=self.pull_request.num
        )
        self.assertEqual(get_first_comment(retrieved).edited, True)
        self.assertEqual(
            get_first_comment(retrieved).id, get_first_comment(self.pull_request).id
        )
        self.assertEqual(get_first_comment(retrieved).content, "**Edited** comment 🤗")

        self.assertEqual(get_first_comment(retrieved), edited_comment)

    def test_comment_discussion(self):
        new_comment = self._api.comment_discussion(
            repo_id=self.repo_name,
            discussion_num=self.discussion.num,
            comment="""\
                # Multi-line comment

                **With formatting**, including *italic text* & ~strike through~
                And even [links](http://hf.co)! 💥🤯
            """,
        )
        retrieved = self._api.get_discussion_details(
            repo_id=self.repo_name, discussion_num=self.discussion.num
        )
        self.assertEqual(len(retrieved.events), 2)
        self.assertIn(new_comment, retrieved.events)

    def test_rename_discussion(self):
        rename_event = self._api.rename_discussion(
            repo_id=self.repo_name,
            discussion_num=self.discussion.num,
            new_title="New titlee",
        )
        retrieved = self._api.get_discussion_details(
            repo_id=self.repo_name, discussion_num=self.discussion.num
        )
        self.assertIn(rename_event, retrieved.events)
        self.assertEqual(rename_event.old_title, self.discussion.title)
        self.assertEqual(rename_event.new_title, "New titlee")

    def test_change_discussion_status(self):
        status_change_event = self._api.change_discussion_status(
            repo_id=self.repo_name,
            discussion_num=self.discussion.num,
            new_status="closed",
        )
        retrieved = self._api.get_discussion_details(
            repo_id=self.repo_name, discussion_num=self.discussion.num
        )
        self.assertIn(status_change_event, retrieved.events)
        self.assertEqual(status_change_event.new_status, "closed")

        with self.assertRaises(ValueError):
            self._api.change_discussion_status(
                repo_id=self.repo_name,
                discussion_num=self.discussion.num,
                new_status="published",
            )

    # @unittest.skip("To unskip when create_commit works for arbitrary references")
    def test_merge_pull_request(self):
        self._api.create_commit(
            repo_id=self.repo_name,
            commit_message="Commit some file",
            operations=[
                CommitOperationAdd(path_in_repo="file.test", path_or_fileobj=b"Content")
            ],
            revision=self.pull_request.git_reference,
        )
        self._api.change_discussion_status(
            repo_id=self.repo_name,
            discussion_num=self.pull_request.num,
            new_status="open",
        )
        self._api.merge_pull_request(self.repo_name, self.pull_request.num)

        retrieved = self._api.get_discussion_details(
            repo_id=self.repo_name, discussion_num=self.pull_request.num
        )
        self.assertEqual(retrieved.status, "merged")
        self.assertIsNotNone(retrieved.merge_commit_oid)


class ActivityApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.api = HfApi()
        return super().setUpClass()

    def test_like_and_unlike_repo(self) -> None:
        # Create and like repo
        repo_id = f"{USER}/{repo_name()}"
        self.api.create_repo(repo_id, token=TOKEN, private=True)
        self.api.like(repo_id, token=TOKEN)

        # Get likes as public and authenticated
        likes = self.api.list_liked_repos(USER)
        likes_with_auth = self.api.list_liked_repos(USER, token=TOKEN)

        # New repo is not public: still see the like, not the repo_id
        self.assertNotIn(repo_id, likes.models)
        self.assertIn(repo_id, likes_with_auth.models)

        # Unlike and check not in liked list
        self.api.unlike(repo_id, token=TOKEN)
        likes_after_unliking_with_auth = self.api.list_liked_repos(USER, token=TOKEN)
        self.assertNotIn(repo_id, likes_after_unliking_with_auth.models)  # Unliked

        # Cleanup
        self.api.delete_repo(repo_id, token=TOKEN)

    def test_like_missing_repo(self) -> None:
        with self.assertRaises(RepositoryNotFoundError):
            self.api.like("missing_repo_id", token=TOKEN)

        with self.assertRaises(RepositoryNotFoundError):
            self.api.unlike("missing_repo_id", token=TOKEN)

    def test_like_twice(self) -> None:
        # Create and like repo
        repo_id = f"{USER}/{repo_name()}"
        self.api.create_repo(repo_id, token=TOKEN, private=True)

        # Can like twice
        self.api.like(repo_id, token=TOKEN)
        self.api.like(repo_id, token=TOKEN)

        # Can unlike twice
        self.api.unlike(repo_id, token=TOKEN)
        self.api.unlike(repo_id, token=TOKEN)

        # Cleanup
        self.api.delete_repo(repo_id, token=TOKEN)

    def test_list_liked_repos_no_auth(self) -> None:
        likes = self.api.list_liked_repos(USER)
        self.assertEqual(likes.user, USER)
        self.assertGreater(
            len(likes.models) + len(likes.datasets) + len(likes.spaces), 0
        )
        self.assertIn(f"{USER}/repo-that-is-liked-public", likes.models)

    def test_list_likes_repos_auth_and_implicit_user(self) -> None:
        # User is implicit
        likes = self.api.list_liked_repos(token=TOKEN)
        self.assertEqual(likes.user, USER)

    def test_list_likes_repos_auth_and_explicit_user(self) -> None:
        # User is explicit even if auth
        likes = self.api.list_liked_repos(
            user="__DUMMY_DATASETS_SERVER_USER__", token=TOKEN
        )
        self.assertEqual(likes.user, "__DUMMY_DATASETS_SERVER_USER__")

    @with_production_testing
    def test_list_likes_on_production(self) -> None:
        # Test julien-c likes a lot of repos !
        likes = HfApi().list_liked_repos("julien-c")
        self.assertEqual(
            len(likes.models) + len(likes.datasets) + len(likes.spaces), likes.total
        )
        self.assertGreater(len(likes.models), 0)
        self.assertGreater(len(likes.datasets), 0)
        self.assertGreater(len(likes.spaces), 0)


@pytest.mark.usefixtures("fx_production_space")
class TestSpaceAPIProduction(unittest.TestCase):
    """
    Testing Space API is not possible on staging. Tests are run against production
    server using a token stored under `HUGGINGFACE_PRODUCTION_USER_TOKEN` environment
    variable. Tests requiring hardware are mocked to spare some resources.
    """

    repo_id: str
    api: HfApi

    def test_manage_secrets(self) -> None:
        # Add 3 secrets
        self.api.add_space_secret(self.repo_id, "foo", "123")
        self.api.add_space_secret(self.repo_id, "token", "hf_api_123456")
        self.api.add_space_secret(self.repo_id, "gh_api_key", "******")

        # Update secret
        self.api.add_space_secret(self.repo_id, "foo", "456")

        # Delete secret
        self.api.delete_space_secret(self.repo_id, "gh_api_key")

        # Doesn't fail on missing key
        self.api.delete_space_secret(self.repo_id, "missing_key")

    def test_space_runtime(self) -> None:
        runtime = self.api.get_space_runtime(self.repo_id)

        # Space has just been created: hardware might not be set yet.
        self.assertIn(runtime.hardware, (None, SpaceHardware.CPU_BASIC))
        self.assertIn(runtime.requested_hardware, (None, SpaceHardware.CPU_BASIC))

        # Space is either "BUILDING" (if not yet done) or "NO_APP_FILE" (if building failed)
        self.assertIn(runtime.stage, (SpaceStage.NO_APP_FILE, SpaceStage.BUILDING))
        self.assertIn(runtime.stage, ("NO_APP_FILE", "BUILDING"))  # str works as well

        # Raw response from Hub
        self.assertIsInstance(runtime.raw, dict)


class TestSpaceAPIMocked(unittest.TestCase):
    """
    Testing Space hardware requests is resource intensive for the server (need to spawn
    GPUs). Tests are mocked to check the correct values are sent.
    """

    def setUp(self) -> None:
        self.api = HfApi(token="fake_token")
        self.repo_id = "fake_repo_id"
        return super().setUp()

    @patch("huggingface_hub.hf_api.requests.post")
    def test_create_space_with_hardware(self, post_mock: Mock) -> None:
        self.api.create_repo(
            self.repo_id,
            repo_type="space",
            space_sdk="gradio",
            space_hardware=SpaceHardware.T4_MEDIUM,
        )
        post_mock.assert_called_once_with(
            f"{self.api.endpoint}/api/repos/create",
            headers=self.api._build_hf_headers(),
            json={
                "name": self.repo_id,
                "organization": None,
                "private": False,
                "type": "space",
                "sdk": "gradio",
                "hardware": "t4-medium",
            },
        )

    @patch("huggingface_hub.hf_api.requests.post")
    def test_request_space_hardware(self, post_mock: Mock) -> None:
        self.api.request_space_hardware(self.repo_id, SpaceHardware.T4_MEDIUM)
        post_mock.assert_called_once_with(
            f"{self.api.endpoint}/api/spaces/{self.repo_id}/hardware",
            headers=self.api._build_hf_headers(),
            json={"flavor": "t4-medium"},
        )


class ListGitRefsTest(unittest.TestCase):
    @classmethod
    @with_production_testing
    def setUpClass(cls) -> None:
        cls.api = HfApi()
        return super().setUpClass()

    def test_list_refs_gpt2(self) -> None:
        refs = self.api.list_repo_refs("gpt2")
        self.assertGreater(len(refs.branches), 0)
        main_branch = [branch for branch in refs.branches if branch.name == "main"][0]
        self.assertEqual(main_branch.ref, "refs/heads/main")
        # Can get info by revision
        self.api.repo_info("gpt2", revision=main_branch.target_commit)

    def test_list_refs_bigcode(self) -> None:
        refs = self.api.list_repo_refs("bigcode/evaluation", repo_type="dataset")
        self.assertGreater(len(refs.branches), 0)
        self.assertGreater(len(refs.converts), 0)
        main_branch = [branch for branch in refs.branches if branch.name == "main"][0]
        self.assertEqual(main_branch.ref, "refs/heads/main")

        convert_branch = [
            branch for branch in refs.converts if branch.name == "parquet"
        ][0]
        self.assertEqual(convert_branch.ref, "refs/convert/parquet")

        # Can get info by convert revision
        self.api.repo_info(
            "bigcode/evaluation",
            repo_type="dataset",
            revision=convert_branch.target_commit,
        )


@patch("huggingface_hub.hf_api.build_hf_headers")
class HfApiTokenAttributeTest(unittest.TestCase):
    def test_token_passed(self, mock_build_hf_headers: Mock) -> None:
        HfApi(token="default token")._build_hf_headers(token="A token")
        self._assert_token_is(mock_build_hf_headers, "A token")

    def test_no_token_passed(self, mock_build_hf_headers: Mock) -> None:
        HfApi(token="default token")._build_hf_headers()
        self._assert_token_is(mock_build_hf_headers, "default token")

    def test_token_true_passed(self, mock_build_hf_headers: Mock) -> None:
        HfApi(token="default token")._build_hf_headers(token=True)
        self._assert_token_is(mock_build_hf_headers, True)

    def test_token_false_passed(self, mock_build_hf_headers: Mock) -> None:
        HfApi(token="default token")._build_hf_headers(token=False)
        self._assert_token_is(mock_build_hf_headers, False)

    def test_no_token_at_all(self, mock_build_hf_headers: Mock) -> None:
        HfApi()._build_hf_headers(token=None)
        self._assert_token_is(mock_build_hf_headers, None)

    def _assert_token_is(
        self, mock_build_hf_headers: Mock, expected_value: str
    ) -> None:
        self.assertEqual(mock_build_hf_headers.call_args[1]["token"], expected_value)

    def test_library_name_and_version_are_set(
        self, mock_build_hf_headers: Mock
    ) -> None:
        HfApi(library_name="a", library_version="b")._build_hf_headers()
        self.assertEqual(mock_build_hf_headers.call_args[1]["library_name"], "a")
        self.assertEqual(mock_build_hf_headers.call_args[1]["library_version"], "b")

    def test_library_name_and_version_are_overwritten(
        self, mock_build_hf_headers: Mock
    ) -> None:
        api = HfApi(library_name="a", library_version="b")
        api._build_hf_headers(library_name="A", library_version="B")
        self.assertEqual(mock_build_hf_headers.call_args[1]["library_name"], "A")
        self.assertEqual(mock_build_hf_headers.call_args[1]["library_version"], "B")

    def test_user_agent_is_set(self, mock_build_hf_headers: Mock) -> None:
        HfApi(user_agent={"a": "b"})._build_hf_headers()
        self.assertEqual(mock_build_hf_headers.call_args[1]["user_agent"], {"a": "b"})

    def test_user_agent_is_overwritten(self, mock_build_hf_headers: Mock) -> None:
        HfApi(user_agent={"a": "b"})._build_hf_headers(user_agent={"A": "B"})
        self.assertEqual(mock_build_hf_headers.call_args[1]["user_agent"], {"A": "B"})


@patch("huggingface_hub.hf_api.ENDPOINT", "https://huggingface.co")
class RepoUrlTest(unittest.TestCase):
    def test_repo_url_class(self):
        url = RepoUrl("https://huggingface.co/gpt2")

        # RepoUrl Is a string
        self.assertIsInstance(url, str)
        self.assertEqual(url, "https://huggingface.co/gpt2")

        # Any str-method can be applied
        self.assertEqual(url.split("/"), "https://huggingface.co/gpt2".split("/"))

        # String formatting and concatenation work
        self.assertEqual(f"New repo: {url}", "New repo: https://huggingface.co/gpt2")
        self.assertEqual("New repo: " + url, "New repo: https://huggingface.co/gpt2")

        # __repr__ is modified for debugging purposes
        self.assertEqual(
            repr(url),
            "RepoUrl('https://huggingface.co/gpt2', endpoint='https://huggingface.co',"
            " repo_type='model', repo_id='gpt2')",
        )

    def test_repo_url_endpoint(self):
        # Implicit endpoint
        url = RepoUrl("https://huggingface.co/gpt2")
        self.assertEqual(url.endpoint, "https://huggingface.co")

        # Explicit endpoint
        url = RepoUrl("https://example.com/gpt2", endpoint="https://example.com")
        self.assertEqual(url.endpoint, "https://example.com")

    def test_repo_url_repo_type(self):
        # Explicit repo type
        url = RepoUrl("https://huggingface.co/user/repo_name")
        self.assertEqual(url.repo_type, "model")

        url = RepoUrl("https://huggingface.co/datasets/user/repo_name")
        self.assertEqual(url.repo_type, "dataset")

        url = RepoUrl("https://huggingface.co/spaces/user/repo_name")
        self.assertEqual(url.repo_type, "space")

        # Implicit repo type (model)
        url = RepoUrl("https://huggingface.co/user/repo_name")
        self.assertEqual(url.repo_type, "model")

    def test_repo_url_namespace(self):
        # Canonical model (e.g. no username)
        url = RepoUrl("https://huggingface.co/gpt2")
        self.assertIsNone(url.namespace)
        self.assertEqual(url.repo_id, "gpt2")

        # "Normal" model
        url = RepoUrl("https://huggingface.co/dummy_user/dummy_model")
        self.assertEqual(url.namespace, "dummy_user")
        self.assertEqual(url.repo_id, "dummy_user/dummy_model")

    def test_repo_url_url_property(self):
        # RepoUrl.url returns a pure `str` value
        url = RepoUrl("https://huggingface.co/gpt2")
        self.assertEqual(url, "https://huggingface.co/gpt2")
        self.assertEqual(url.url, "https://huggingface.co/gpt2")
        self.assertIsInstance(url, RepoUrl)
        self.assertNotIsInstance(url.url, RepoUrl)
