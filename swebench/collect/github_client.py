"""
GitHub API client implementation for SWE-bench data collection.

This module provides a GitHub-specific implementation of the PlatformClient interface,
using the ghapi library to interact with the GitHub REST API.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Callable, Iterator, Optional

from fastcore.net import HTTP403ForbiddenError, HTTP404NotFoundError
from ghapi.core import GhApi

from swebench.collect.platform_client import PlatformClient

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# GitHub issue resolution keywords
# https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/using-keywords-in-issues-and-pull-requests
GITHUB_KEYWORDS = {
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
}


class GitHubClient(PlatformClient):
    """GitHub API client implementation"""

    def __init__(self, owner: str, name: str, token: Optional[str] = None):
        """
        Initialize GitHub API client.

        Args:
            owner: Repository owner (user or organization)
            name: Repository name
            token: GitHub Personal Access Token (optional but recommended for rate limits)
        """
        self.owner = owner
        self.name = name
        self.token = token
        self.api = GhApi(token=token)
        self.repo = self.call_api(self.api.repos.get, owner=owner, repo=name)

    def call_api(self, func: Callable, **kwargs) -> dict | None:
        """
        API call wrapper with rate limit handling.

        Checks rate limits every 5 minutes if exceeded.

        Args:
            func: API function to call
            **kwargs: Keyword arguments to pass to API function

        Returns:
            Response object from func, or None if not found
        """
        while True:
            try:
                values = func(**kwargs)
                return values
            except HTTP403ForbiddenError:
                while True:
                    rl = self.api.rate_limit.get()
                    logger.info(
                        f"[{self.owner}/{self.name}] Rate limit exceeded for token {self.token[:10] if self.token else 'None'}, "
                        f"waiting for 5 minutes, remaining calls: {rl.resources.core.remaining}"
                    )
                    if rl.resources.core.remaining > 0:
                        break
                    time.sleep(60 * 5)
            except HTTP404NotFoundError:
                logger.info(f"[{self.owner}/{self.name}] Resource not found {kwargs}")
                return None

    def get_all_loop(
        self,
        func: Callable,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        quiet: bool = False,
        **kwargs,
    ) -> Iterator:
        """
        Return all values from a paginated API endpoint.

        Args:
            func: API function to call
            per_page: Number of values to return per page
            num_pages: Maximum number of pages to fetch (None = all)
            quiet: If True, suppress progress logging
            **kwargs: Additional keyword arguments to pass to API function

        Yields:
            Items from paginated API responses
        """
        page = 1
        args = {
            "owner": self.owner,
            "repo": self.name,
            "per_page": per_page,
            **kwargs,
        }
        while True:
            try:
                # Get values from API call
                values = func(**args, page=page)
                yield from values
                if len(values) == 0:
                    break
                if not quiet:
                    rl = self.api.rate_limit.get()
                    logger.info(
                        f"[{self.owner}/{self.name}] Processed page {page} ({per_page} values per page). "
                        f"Remaining calls: {rl.resources.core.remaining}"
                    )
                if num_pages is not None and page >= num_pages:
                    break
                page += 1
            except Exception as e:
                # Rate limit handling
                logger.error(
                    f"[{self.owner}/{self.name}] Error processing page {page} "
                    f"w/ token {self.token[:10] if self.token else 'None'} - {e}"
                )
                while True:
                    rl = self.api.rate_limit.get()
                    if rl.resources.core.remaining > 0:
                        break
                    logger.info(
                        f"[{self.owner}/{self.name}] Waiting for rate limit reset "
                        f"for token {self.token[:10] if self.token else 'None'}, checking again in 5 minutes"
                    )
                    time.sleep(60 * 5)
        if not quiet:
            logger.info(
                f"[{self.owner}/{self.name}] Processed {(page - 1) * per_page + len(values)} values"
            )

    def get_all_pulls(
        self,
        per_page: int = 100,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """Get all pull requests from the repository"""
        pulls = self.get_all_loop(
            self.api.pulls.list,
            per_page=per_page,
            direction=direction,
            sort=sort,
            state=state,
            quiet=quiet,
        )
        return pulls

    def get_pull(self, pull_number: int) -> Optional[dict]:
        """Get a specific pull request by number"""
        pull = self.call_api(
            self.api.pulls.get,
            owner=self.owner,
            repo=self.name,
            pull_number=pull_number,
        )
        return pull

    def get_issue(self, issue_number: int) -> Optional[dict]:
        """Get a specific issue by number"""
        issue = self.call_api(
            self.api.issues.get,
            owner=self.owner,
            repo=self.name,
            issue_number=issue_number,
        )
        return issue

    def get_pull_commits(self, pull_number: int) -> list:
        """Get all commits in a pull request"""
        commits = list(
            self.get_all_loop(
                self.api.pulls.list_commits, pull_number=pull_number, quiet=True
            )
        )
        return commits

    def get_issue_comments(self, issue_number: int) -> list:
        """Get all comments on an issue"""
        comments = list(
            self.get_all_loop(
                self.api.issues.list_comments, issue_number=issue_number, quiet=True
            )
        )
        return comments

    def get_diff_url(self, pull: dict) -> str:
        """Get the URL to fetch the diff for a pull request"""
        return pull.get("diff_url", "")

    def extract_resolved_issues(self, pull: dict) -> list[str]:
        """
        Extract list of issues referenced by a PR using GitHub keywords.

        Searches PR title, body, and commit messages for patterns like:
        - "fixes #123"
        - "closes #456"
        - "resolves #789"

        Args:
            pull: PR dictionary object from GitHub

        Returns:
            List of issue numbers (as strings) referenced by PR
        """
        # Define regex patterns
        issues_pat = re.compile(r"(\w+)\s+\#(\d+)")
        comments_pat = re.compile(r"(?s)<!--.*?-->")

        # Construct text to search
        text = pull.get("title", "") if pull.get("title") else ""
        text += "\n" + (pull.get("body", "") if pull.get("body") else "")

        # Add commit messages
        commits = self.get_pull_commits(pull.get("number"))
        commit_messages = [
            commit.commit.message for commit in commits if hasattr(commit, "commit")
        ]
        commit_text = "\n".join(commit_messages) if commit_messages else ""
        text += "\n" + commit_text

        # Remove HTML comments
        text = comments_pat.sub("", text)

        # Look for issue numbers with keywords
        references = issues_pat.findall(text)
        resolved_issues_set = set()
        if references:
            for word, issue_num in references:
                if word.lower() in GITHUB_KEYWORDS:
                    resolved_issues_set.add(issue_num)

        return list(resolved_issues_set)

    def get_clone_url(self, repo_name: str) -> str:
        """Get the git clone URL for the repository"""
        return f"https://github.com/{repo_name}"

    def get_raw_file_url(self, repo_name: str, commit: str, file_path: str) -> str:
        """Get URL to fetch a raw file at a specific commit"""
        return f"https://raw.githubusercontent.com/{repo_name}/{commit}/{file_path}"
