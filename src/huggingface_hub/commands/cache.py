# coding=utf-8
# Copyright 2022-present, the HuggingFace Inc. team.
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
"""Contains commands to manage the HF cache directory."""
import time
from argparse import ArgumentParser
from typing import Optional

from ..utils import HFCacheInfo, scan_cache_dir
from . import BaseHuggingfaceCLICommand
from ._cli_utils import ANSI, tabulate


class ScanCacheCommand(BaseHuggingfaceCLICommand):
    @staticmethod
    def register_subcommand(parser: ArgumentParser):
        scan_cache_parser = parser.add_parser(
            "scan-cache", help="Scan cache directory."
        )

        scan_cache_parser.add_argument(
            "--dir",
            type=str,
            default=None,
            help=(
                "cache directory to scan (optional). Default to the"
                " default HuggingFace cache."
            ),
        )
        scan_cache_parser.add_argument(
            "-v",
            "--verbose",
            action="count",
            default=0,
            help="show a more verbose output",
        )
        scan_cache_parser.set_defaults(func=ScanCacheCommand)

    def __init__(self, args):
        self.verbosity: int = args.verbose
        self.cache_dir: Optional[str] = args.dir

    def run(self):
        t0 = time.time()
        hf_cache_info = scan_cache_dir(self.cache_dir)
        t1 = time.time()

        self._print_hf_cache_info_as_table(hf_cache_info)

        print(
            f"\nDone in {round(t1-t0,1)}s. Scanned {len(hf_cache_info.repos)} repo(s)"
            f" for a total of {ANSI.red(hf_cache_info.size_on_disk_str)}."
        )
        if len(hf_cache_info.errors) > 0:
            message = f"Got {len(hf_cache_info.errors)} error(s) while scanning."
            if self.verbosity >= 3:
                print(ANSI.gray(message))
                for error in hf_cache_info.errors:
                    print(ANSI.gray(error))
            else:
                print(ANSI.gray(message + " Use -vvv to print details."))

    def _print_hf_cache_info_as_table(self, hf_cache_info: HFCacheInfo) -> None:
        if self.verbosity == 0:
            print(
                tabulate(
                    rows=[
                        [
                            repo.repo_id,
                            repo.repo_type,
                            "{:>12}".format(repo.size_on_disk_str),
                            repo.nb_files,
                            ", ".join(sorted(repo.refs)),
                            str(repo.repo_path),
                        ]
                        for repo in sorted(
                            hf_cache_info.repos, key=lambda repo: repo.repo_path
                        )
                    ],
                    headers=[
                        "REPO ID",
                        "REPO TYPE",
                        "SIZE ON DISK",
                        "NB FILES",
                        "REFS",
                        "LOCAL PATH",
                    ],
                )
            )
        else:
            print(
                tabulate(
                    rows=[
                        [
                            repo.repo_id,
                            repo.repo_type,
                            revision.commit_hash,
                            "{:>12}".format(revision.size_on_disk_str),
                            revision.nb_files,
                            ", ".join(sorted(revision.refs)),
                            str(revision.snapshot_path),
                        ]
                        for repo in sorted(
                            hf_cache_info.repos, key=lambda repo: repo.repo_path
                        )
                        for revision in sorted(
                            repo.revisions, key=lambda revision: revision.commit_hash
                        )
                    ],
                    headers=[
                        "REPO ID",
                        "REPO TYPE",
                        "REVISION",
                        "SIZE ON DISK",
                        "NB FILES",
                        "REFS",
                        "LOCAL PATH",
                    ],
                )
            )
