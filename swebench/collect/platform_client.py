"""
Platform-agnostic client interface for collecting data from GitHub, GitLab, and other platforms.

This module defines abstract base classes that provide a unified interface for interacting
with different code hosting platforms (GitHub, GitLab, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, Optional


class PlatformClient(ABC):
    """Abstract base class for platform API clients (GitHub, GitLab, etc.)"""

    @abstractmethod
    def get_all_pulls(
        self,
        per_page: int = 100,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """
        Get all pull requests/merge requests from the repository.

        Args:
            per_page: Number of items to return per page
            direction: Sort direction ('asc' or 'desc')
            sort: Field to sort by ('created', 'updated', etc.)
            state: State of PRs to fetch ('open', 'closed', 'all')
            quiet: If True, suppress progress logging

        Returns:
            Iterator yielding PR/MR objects
        """
        pass

    @abstractmethod
    def get_pull(self, pull_number: int) -> Optional[dict]:
        """
        Get a specific pull request/merge request by number.

        Args:
            pull_number: The PR/MR number

        Returns:
            Dictionary containing PR/MR data, or None if not found
        """
        pass

    @abstractmethod
    def get_issue(self, issue_number: int) -> Optional[dict]:
        """
        Get a specific issue by number.

        Args:
            issue_number: The issue number

        Returns:
            Dictionary containing issue data, or None if not found
        """
        pass

    @abstractmethod
    def get_pull_commits(self, pull_number: int) -> list:
        """
        Get all commits in a pull request/merge request.

        Args:
            pull_number: The PR/MR number

        Returns:
            List of commit objects
        """
        pass

    @abstractmethod
    def get_issue_comments(self, issue_number: int) -> list:
        """
        Get all comments on an issue.

        Args:
            issue_number: The issue number

        Returns:
            List of comment objects
        """
        pass

    @abstractmethod
    def get_diff_url(self, pull: dict) -> str:
        """
        Get the URL to fetch the diff/patch for a pull request.

        Args:
            pull: Pull request dictionary object

        Returns:
            URL string where the diff can be downloaded
        """
        pass

    @abstractmethod
    def extract_resolved_issues(self, pull: dict) -> list[str]:
        """
        Extract list of issue numbers that are resolved/closed by this PR.

        Parses PR title, body, and commit messages for keywords like
        "fixes #123", "closes #456", etc.

        Args:
            pull: Pull request dictionary object

        Returns:
            List of issue numbers (as strings) referenced by the PR
        """
        pass

    @abstractmethod
    def get_clone_url(self, repo_name: str) -> str:
        """
        Get the git clone URL for the repository.

        Args:
            repo_name: Repository identifier (e.g., "owner/repo")

        Returns:
            Git clone URL string
        """
        pass

    @abstractmethod
    def get_raw_file_url(self, repo_name: str, commit: str, file_path: str) -> str:
        """
        Get URL to fetch a raw file at a specific commit.

        Args:
            repo_name: Repository identifier (e.g., "owner/repo")
            commit: Commit SHA
            file_path: Path to file within repository

        Returns:
            URL string where the raw file can be downloaded
        """
        pass


def detect_platform(repo_identifier: str) -> str:
    """
    Detect the platform (github or gitlab) from a repository identifier.

    Args:
        repo_identifier: Repository string (e.g., "owner/repo", "gitlab.com/group/project")

    Returns:
        Platform string: 'github' or 'gitlab'
    """
    # Explicit GitLab indicators
    if "gitlab.com" in repo_identifier.lower() or "gitlab" in repo_identifier.lower():
        return "gitlab"

    # Count path segments (GitLab often has nested groups: group/subgroup/project)
    segments = repo_identifier.strip("/").split("/")
    if len(segments) > 2:
        # More than 2 segments suggests nested GitLab groups
        return "gitlab"

    # Default to GitHub for backward compatibility
    return "github"
