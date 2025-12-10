"""
GitLab API client implementation for SWE-bench data collection.

This module provides a GitLab-specific implementation of the PlatformClient interface,
using the python-gitlab library to interact with the GitLab REST API.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Iterator, Optional

import gitlab

from swebench.collect.platform_client import PlatformClient

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# GitLab issue resolution keywords
# https://docs.gitlab.com/ee/user/project/issues/managing_issues.html#closing-issues-automatically
# Extended to include references that don't auto-close but indicate the MR addresses the issue
GITLAB_KEYWORDS = {
    # Auto-closing keywords (official GitLab)
    "close",
    "closes",
    "closed",
    "closing",
    "fix",
    "fixes",
    "fixed",
    "fixing",
    "resolve",
    "resolves",
    "resolved",
    "resolving",
    "implement",
    "implements",
    "implemented",
    "implementing",
    # Reference keywords (for SWE-bench - indicate MR addresses issue)
    "relate",
    "relates",
    "related",
    "relating",
    "address",
    "addresses",
    "addressed",
    "addressing",
    "ref",
    "refs",
    "references",
    "referenced",
    "referencing",
    "see",
    "part",
}


class GitLabClient(PlatformClient):
    """GitLab API client implementation"""

    def __init__(
        self,
        project_path: str,
        token: Optional[str] = None,
        gitlab_url: str = "https://gitlab.com",
    ):
        """
        Initialize GitLab API client.

        Args:
            project_path: Full project path (e.g., "gitlab-org/gitlab" or "group/subgroup/project")
            token: GitLab Personal Access Token with read_api scope
            gitlab_url: GitLab instance URL (default: https://gitlab.com)
        """
        self.project_path = project_path
        self.token = token
        self.gitlab_url = gitlab_url

        # Initialize GitLab connection
        self.gl = gitlab.Gitlab(gitlab_url, private_token=token)

        # Get project (python-gitlab handles URL encoding internally)
        try:
            self.project = self.gl.projects.get(project_path)
            logger.info(f"[{project_path}] Successfully connected to GitLab project")
        except gitlab.exceptions.GitlabGetError as e:
            logger.error(f"[{project_path}] Failed to get project: {e}")
            raise

    def _handle_rate_limit(self):
        """Handle GitLab rate limiting with exponential backoff"""
        # GitLab.com public API: 300 req/hr unauthenticated, 2000 req/hr authenticated
        logger.info(
            f"[{self.project_path}] Rate limit may be exceeded, waiting 5 minutes"
        )
        time.sleep(60 * 5)

    def _normalize_mr_to_pr(self, mr) -> dict:
        """
        Normalize GitLab MR object to look like a GitHub PR object.

        Args:
            mr: GitLab MergeRequest object

        Returns:
            Dictionary with GitHub PR-like structure
        """
        # Get base commit SHA (target branch)
        base_commit = None
        if hasattr(mr, "diff_refs") and mr.diff_refs:
            base_commit = getattr(mr.diff_refs, "base_sha", None)
        # Fallback: try sha attribute directly
        if not base_commit and hasattr(mr, "sha"):
            base_commit = mr.sha

        return {
            "number": mr.iid,  # GitLab uses 'iid' (internal ID), not 'id'
            "title": mr.title,
            "body": mr.description,
            "state": mr.state,  # 'opened', 'closed', 'merged'
            "created_at": mr.created_at,
            "updated_at": mr.updated_at,
            "merged_at": mr.merged_at if hasattr(mr, "merged_at") else None,
            "diff_url": f"{self.gitlab_url}/{self.project_path}/-/merge_requests/{mr.iid}.diff",
            "web_url": mr.web_url,
            "source_branch": mr.source_branch,
            "target_branch": mr.target_branch,
            "author": mr.author if hasattr(mr, "author") else None,
            "base_commit": base_commit,  # Base commit SHA for task instance creation
            "repo": self.project_path,  # Add repo identifier
        }

    def get_all_pulls(
        self,
        per_page: int = 100,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """
        Get all merge requests from the repository.

        Args:
            per_page: Number of items per page
            direction: Sort direction ('asc' or 'desc')
            sort: Field to sort by ('created', 'updated')
            state: State filter ('open', 'closed', 'merged', 'all')
            quiet: If True, suppress progress logging

        Yields:
            Normalized MR objects (as dictionaries)
        """
        # Map GitHub state to GitLab state
        state_map = {
            "closed": "merged",  # GitHub 'closed' typically means merged
            "open": "opened",  # GitLab uses 'opened'
            "all": "all",
        }
        gitlab_state = state_map.get(state, state)

        # Map sort field
        order_by = "created_at" if sort == "created" else "updated_at"

        # Map direction
        sort_order = "desc" if direction == "desc" else "asc"

        try:
            # Get all merge requests with pagination
            mrs = self.project.mergerequests.list(
                state=gitlab_state,
                order_by=order_by,
                sort=sort_order,
                per_page=per_page,
                get_all=True,  # python-gitlab handles pagination automatically
            )

            for i, mr in enumerate(mrs):
                if not quiet and i > 0 and i % per_page == 0:
                    logger.info(f"[{self.project_path}] Processed {i} merge requests")
                yield self._normalize_mr_to_pr(mr)

            if not quiet:
                logger.info(
                    f"[{self.project_path}] Processed {len(mrs)} merge requests total"
                )

        except gitlab.exceptions.GitlabListError as e:
            logger.error(f"[{self.project_path}] Error fetching merge requests: {e}")
            if "429" in str(e):  # Rate limit
                self._handle_rate_limit()

    def get_pull(self, pull_number: int) -> Optional[dict]:
        """Get a specific merge request by IID"""
        try:
            mr = self.project.mergerequests.get(pull_number)
            return self._normalize_mr_to_pr(mr)
        except gitlab.exceptions.GitlabGetError as e:
            logger.info(f"[{self.project_path}] MR #{pull_number} not found: {e}")
            return None

    def get_issue(self, issue_number: int) -> Optional[dict]:
        """Get a specific issue by IID"""
        try:
            issue = self.project.issues.get(issue_number)
            return {
                "number": issue.iid,
                "title": issue.title,
                "body": issue.description,
                "state": issue.state,
                "created_at": issue.created_at,
                "updated_at": issue.updated_at,
            }
        except gitlab.exceptions.GitlabGetError as e:
            logger.info(f"[{self.project_path}] Issue #{issue_number} not found: {e}")
            return None

    def get_pull_commits(self, pull_number: int) -> list:
        """Get all commits in a merge request"""
        try:
            mr = self.project.mergerequests.get(pull_number)
            commits = list(mr.commits())

            # Normalize to look like GitHub commit objects
            normalized_commits = []
            for commit in commits:
                normalized_commits.append(
                    {
                        "sha": commit.id,
                        "commit": {
                            "message": commit.message,
                            "author": {
                                "name": (
                                    commit.author_name
                                    if hasattr(commit, "author_name")
                                    else None
                                ),
                                "email": (
                                    commit.author_email
                                    if hasattr(commit, "author_email")
                                    else None
                                ),
                                "date": (
                                    commit.created_at
                                    if hasattr(commit, "created_at")
                                    else None
                                ),
                            },
                        },
                    }
                )
            return normalized_commits
        except gitlab.exceptions.GitlabGetError as e:
            logger.error(
                f"[{self.project_path}] Error getting commits for MR #{pull_number}: {e}"
            )
            return []

    def get_issue_comments(self, issue_number: int) -> list:
        """Get all comments (notes) on an issue"""
        try:
            issue = self.project.issues.get(issue_number)
            notes = issue.notes.list(get_all=True)

            # Normalize to look like GitHub comments
            normalized_comments = []
            for note in notes:
                normalized_comments.append(
                    {
                        "id": note.id,
                        "body": note.body,
                        "created_at": note.created_at,
                        "updated_at": note.updated_at,
                        "author": note.author if hasattr(note, "author") else None,
                    }
                )
            return normalized_comments
        except (
            gitlab.exceptions.GitlabGetError,
            gitlab.exceptions.GitlabAuthenticationError,
        ) as e:
            logger.warning(
                f"[{self.project_path}] Could not fetch comments for issue #{issue_number}: {e}"
            )
            logger.warning(
                f"[{self.project_path}] Continuing without comments (hints). This may be due to python-gitlab library limitations."
            )
            return []

    def get_diff_url(self, pull: dict) -> str:
        """Get the URL to fetch the diff for a merge request"""
        return pull.get("diff_url", "")

    def extract_resolved_issues(self, pull: dict) -> list[str]:
        """
        Extract list of issues referenced by an MR using GitLab keywords.

        GitLab supports multiple formats:
        - "Closes #123"
        - "Fixes gitlab-org/gitlab#456"
        - "Resolves https://gitlab.com/gitlab-org/gitlab/-/issues/789"

        Args:
            pull: MR dictionary object

        Returns:
            List of issue numbers (as strings) referenced by MR
        """
        # Regex patterns for different formats
        # Format 1: "Closes #123" or "Relates to issue #123"
        simple_pat = re.compile(r"(\w+)(?:\s+\w+)*?\s+\#(\d+)", re.IGNORECASE)

        # Format 2: "Closes owner/repo#123" or "Relates to owner/repo#123"
        cross_project_pat = re.compile(
            r"(\w+)(?:\s+\w+)*?\s+[\w\-/]+\#(\d+)", re.IGNORECASE
        )

        # Format 3: "Closes https://..." or "Relates to issue https://..."
        url_pat = re.compile(
            r"(\w+)(?:\s+\w+)*?\s+https?://[^/]+/[^/]+/[^/]+(?:/[^/]+)*/-/issues/(\d+)",
            re.IGNORECASE,
        )

        # Remove HTML comments
        comments_pat = re.compile(r"(?s)<!--.*?-->")

        # Construct text to search
        text = pull.get("title", "") if pull.get("title") else ""
        text += "\n" + (pull.get("body", "") if pull.get("body") else "")

        # Add commit messages
        try:
            commits = self.get_pull_commits(pull.get("number"))
            commit_messages = []
            for commit in commits:
                if isinstance(commit, dict) and "commit" in commit:
                    commit_messages.append(commit["commit"]["message"])
            commit_text = "\n".join(commit_messages) if commit_messages else ""
            text += "\n" + commit_text
        except Exception as e:
            logger.warning(
                f"[{self.project_path}] Could not fetch commits for issue resolution: {e}"
            )

        # Remove comments
        text = comments_pat.sub("", text)

        # Search for issue references
        resolved_issues_set = set()

        # Search all three patterns
        for pattern in [simple_pat, cross_project_pat, url_pat]:
            references = pattern.findall(text)
            if references:
                for word, issue_num in references:
                    if word.lower() in GITLAB_KEYWORDS:
                        resolved_issues_set.add(issue_num)

        return list(resolved_issues_set)

    def get_clone_url(self, repo_name: str) -> str:
        """Get the git clone URL for the repository"""
        return f"{self.gitlab_url}/{repo_name}.git"

    def get_raw_file_url(self, repo_name: str, commit: str, file_path: str) -> str:
        """Get URL to fetch a raw file at a specific commit"""
        return f"{self.gitlab_url}/{repo_name}/-/raw/{commit}/{file_path}"
