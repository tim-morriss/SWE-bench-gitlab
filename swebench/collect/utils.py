from __future__ import annotations

import logging
import re
import time
import warnings
from typing import Callable, Iterator, Optional, Union

import requests
from bs4 import BeautifulSoup
from fastcore.net import HTTP403ForbiddenError, HTTP404NotFoundError
from ghapi.core import GhApi
from unidiff import PatchSet

from swebench.collect.github_client import GitHubClient
from swebench.collect.gitlab_client import GitLabClient
from swebench.collect.platform_client import PlatformClient, detect_platform

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/using-keywords-in-issues-and-pull-requests
PR_KEYWORDS = {
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


def create_client(
    repo_identifier: str,
    token: Optional[str] = None,
    platform: Optional[str] = None,
    gitlab_url: str = "https://gitlab.com",
) -> PlatformClient:
    """
    Create a platform client (GitHub or GitLab) based on the repository identifier.

    Args:
        repo_identifier: Repository string (e.g., "owner/repo" or "group/project")
        token: API token (GITHUB_TOKEN or GITLAB_TOKEN)
        platform: Explicit platform ('github' or 'gitlab'). If None, auto-detects.
        gitlab_url: GitLab instance URL (only used for GitLab)

    Returns:
        PlatformClient instance (GitHubClient or GitLabClient)
    """
    # Detect platform if not explicitly specified
    if platform is None:
        platform = detect_platform(repo_identifier)

    if platform == "gitlab":
        return GitLabClient(repo_identifier, token=token, gitlab_url=gitlab_url)
    else:
        # GitHub: split into owner/name
        parts = repo_identifier.split("/")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid GitHub repo format: {repo_identifier}. Expected 'owner/repo'"
            )
        owner, name = parts
        return GitHubClient(owner, name, token=token)


class Repo:
    """
    DEPRECATED: Use create_client() and PlatformClient instead.

    This class is kept for backward compatibility but will be removed in a future version.
    """

    def __init__(self, owner: str, name: str, token: Optional[str] = None):
        """
        Init to retrieve target repository and create ghapi tool

        Args:
            owner (str): owner of target repository
            name (str): name of target repository
            token (str): github token
        """
        warnings.warn(
            "Repo class is deprecated. Use create_client() with PlatformClient instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.owner = owner
        self.name = name
        self.token = token
        self.api = GhApi(token=token)
        self.repo = self.call_api(self.api.repos.get, owner=owner, repo=name)

    def call_api(self, func: Callable, **kwargs) -> dict | None:
        """
        API call wrapper with rate limit handling (checks every 5 minutes if rate limit is reset)

        Args:
            func (callable): API function to call
            **kwargs: keyword arguments to pass to API function
        Return:
            values (dict): response object of `func`
        """
        while True:
            try:
                values = func(**kwargs)
                return values
            except HTTP403ForbiddenError:
                while True:
                    rl = self.api.rate_limit.get()
                    logger.info(
                        f"[{self.owner}/{self.name}] Rate limit exceeded for token {self.token[:10]}, "
                        f"waiting for 5 minutes, remaining calls: {rl.resources.core.remaining}"
                    )
                    if rl.resources.core.remaining > 0:
                        break
                    time.sleep(60 * 5)
            except HTTP404NotFoundError:
                logger.info(f"[{self.owner}/{self.name}] Resource not found {kwargs}")
                return None

    def extract_resolved_issues(self, pull: dict) -> list[str]:
        """
        Extract list of issues referenced by a PR

        Args:
            pull (dict): PR dictionary object from GitHub
        Return:
            resolved_issues (list): list of issue numbers referenced by PR
        """
        # Define 1. issue number regex pattern 2. comment regex pattern 3. keywords
        issues_pat = re.compile(r"(\w+)\s+\#(\d+)")
        comments_pat = re.compile(r"(?s)<!--.*?-->")

        # Construct text to search over for issue numbers from PR body and commit messages
        text = pull.title if pull.title else ""
        text += "\n" + (pull.body if pull.body else "")
        commits = self.get_all_loop(
            self.api.pulls.list_commits, pull_number=pull.number, quiet=True
        )
        commit_messages = [commit.commit.message for commit in commits]
        commit_text = "\n".join(commit_messages) if commit_messages else ""
        text += "\n" + commit_text
        # Remove comments from text
        text = comments_pat.sub("", text)
        # Look for issue numbers in text via scraping <keyword, number> patterns
        references = issues_pat.findall(text)
        resolved_issues_set = set()
        if references:
            for word, issue_num in references:
                if word.lower() in PR_KEYWORDS:
                    resolved_issues_set.add(issue_num)
        return list(resolved_issues_set)

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
            func (callable): API function to call
            per_page (int): number of values to return per page
            num_pages (int): number of pages to return
            quiet (bool): whether to print progress
            **kwargs: keyword arguments to pass to API function
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
                    f"w/ token {self.token[:10]} - {e}"
                )
                while True:
                    rl = self.api.rate_limit.get()
                    if rl.resources.core.remaining > 0:
                        break
                    logger.info(
                        f"[{self.owner}/{self.name}] Waiting for rate limit reset "
                        f"for token {self.token[:10]}, checking again in 5 minutes"
                    )
                    time.sleep(60 * 5)
        if not quiet:
            logger.info(
                f"[{self.owner}/{self.name}] Processed {(page - 1) * per_page + len(values)} values"
            )

    def get_all_issues(
        self,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """
        Wrapper for API call to get all issues from repo

        Args:
            per_page (int): number of issues to return per page
            num_pages (int): number of pages to return
            direction (str): direction to sort issues
            sort (str): field to sort issues by
            state (str): state of issues to look for
            quiet (bool): whether to print progress
        """
        issues = self.get_all_loop(
            self.api.issues.list_for_repo,
            num_pages=num_pages,
            per_page=per_page,
            direction=direction,
            sort=sort,
            state=state,
            quiet=quiet,
        )
        return issues

    def get_all_pulls(
        self,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """
        Wrapper for API call to get all PRs from repo

        Args:
            per_page (int): number of PRs to return per page
            num_pages (int): number of pages to return
            direction (str): direction to sort PRs
            sort (str): field to sort PRs by
            state (str): state of PRs to look for
            quiet (bool): whether to print progress
        """
        pulls = self.get_all_loop(
            self.api.pulls.list,
            num_pages=num_pages,
            direction=direction,
            per_page=per_page,
            sort=sort,
            state=state,
            quiet=quiet,
        )
        return pulls


def extract_problem_statement_and_hints(
    pull: dict, repo: Union[Repo, PlatformClient]
) -> tuple[str, str]:
    """
    Extract problem statement from issues associated with a pull request

    Args:
        pull (dict): PR dictionary object from GitHub/GitLab
        repo: Repo object (deprecated) or PlatformClient instance
    Return:
        text (str): problem statement
        hints (str): hints
    """
    # Handle Django special case (GitHub only)
    repo_name = (
        repo.name if isinstance(repo, Repo) else repo.project_path.split("/")[-1]
    )
    if repo_name == "django" and isinstance(repo, (Repo, GitHubClient)):
        return extract_problem_statement_and_hints_django(pull, repo)

    text = ""
    all_hint_texts = list()

    # Check if we have issue_references with project info (GitLab cross-project support)
    issue_references = pull.get("issue_references", [])
    if not issue_references and "resolved_issues" in pull:
        # Fallback: create references from resolved_issues (assume same project)
        current_project = (
            repo.project_path
            if isinstance(repo, GitLabClient)
            else f"{repo.owner}/{repo.name}"
            if isinstance(repo, Repo)
            else None
        )
        issue_references = [
            {"number": num, "project": current_project}
            for num in pull["resolved_issues"]
        ]

    # Cache for cross-project clients
    cross_project_clients = {}

    for issue_ref in issue_references:
        issue_number = (
            issue_ref.get("number") if isinstance(issue_ref, dict) else issue_ref
        )
        issue_project = (
            issue_ref.get("project") if isinstance(issue_ref, dict) else None
        )

        # Determine which client to use
        issue_client = repo
        if (
            isinstance(repo, GitLabClient)
            and issue_project
            and issue_project != repo.project_path
        ):
            # Cross-project issue - need different client
            if issue_project not in cross_project_clients:
                logger.info(
                    f"[{repo.project_path}] Creating client for cross-project issue in {issue_project}"
                )
                try:
                    cross_project_clients[issue_project] = GitLabClient(
                        issue_project, token=repo.token, gitlab_url=repo.gitlab_url
                    )
                except Exception as e:
                    logger.error(
                        f"[{repo.project_path}] Failed to create client for {issue_project}: {e}"
                    )
                    continue
            issue_client = cross_project_clients[issue_project]

        # Fetch issue using appropriate client
        if isinstance(repo, Repo):
            # Old Repo class
            issue = repo.call_api(
                repo.api.issues.get,
                owner=repo.owner,
                repo=repo.name,
                issue_number=issue_number,
            )
        else:
            # New PlatformClient
            issue = issue_client.get_issue(int(issue_number))

        if issue is None:
            logger.warning(
                f"[{repo.project_path}] Issue #{issue_number} not found in {issue_project or 'same project'}"
            )
            continue

        # Handle different response formats
        if isinstance(repo, Repo):
            title = issue.title if issue.title else ""
            body = issue.body if issue.body else ""
            issue_num = issue.number
        else:
            title = issue.get("title", "")
            body = issue.get("body", "")
            issue_num = issue.get("number")

        text += f"{title}\n{body}\n"

        # Extract hints using the same client (cross-project or not)
        hint_texts = _extract_hints(pull, issue_client, issue_num)
        hint_text = "\n".join(hint_texts)
        all_hint_texts.append(hint_text)

    return text, "\n".join(all_hint_texts) if all_hint_texts else ""


def _extract_hints(
    pull: dict, repo: Union[Repo, PlatformClient], issue_number: int
) -> list[str]:
    """
    Extract hints from comments associated with a pull request (before first commit)

    Args:
        pull (dict): PR dictionary object from GitHub/GitLab
        repo: Repo object (deprecated) or PlatformClient instance
        issue_number (int): issue number
    Return:
        hints (list): list of hints
    """
    # Get all commits in PR
    if isinstance(repo, Repo):
        commits = list(
            repo.get_all_loop(
                repo.api.pulls.list_commits, pull_number=pull["number"], quiet=True
            )
        )
    else:
        commits = repo.get_pull_commits(pull["number"])
    if len(commits) == 0:
        # If there are no comments, return no hints
        return []

    # Get time of first commit in PR
    if isinstance(repo, Repo):
        commit_time_str = commits[0].commit.author.date
    else:
        # New PlatformClient returns dicts
        commit_time_str = commits[0]["commit"]["author"]["date"]

    # Parse timestamp - handle both Z (UTC) and timezone offset formats
    try:
        commit_time = time.mktime(time.strptime(commit_time_str, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        # Try ISO 8601 format with timezone (GitLab format)
        from datetime import datetime

        dt = datetime.fromisoformat(commit_time_str.replace("Z", "+00:00"))
        commit_time = dt.timestamp()

    # Get all comments in PR
    if isinstance(repo, Repo):
        all_comments = list(
            repo.get_all_loop(
                repo.api.issues.list_comments, issue_number=issue_number, quiet=True
            )
        )
    else:
        all_comments = repo.get_issue_comments(issue_number)
    # Iterate through all comments, only keep comments created before first commit
    comments = list()
    for comment in all_comments:
        if isinstance(repo, Repo):
            comment_time_str = comment.updated_at
            comment_body = comment.body
        else:
            # New PlatformClient returns dicts
            comment_time_str = comment.get("updated_at", comment.get("created_at"))
            comment_body = comment.get("body", "")

        # Parse timestamp - handle both Z (UTC) and timezone offset formats
        try:
            comment_time = time.mktime(
                time.strptime(comment_time_str, "%Y-%m-%dT%H:%M:%SZ")
            )
        except ValueError:
            # Try ISO 8601 format with timezone (GitLab format)
            from datetime import datetime

            dt = datetime.fromisoformat(comment_time_str.replace("Z", "+00:00"))
            comment_time = dt.timestamp()
        if comment_time < commit_time:
            comments.append(comment_body)
        else:
            break
        # only include information available before the first commit was created
    return comments


def extract_patches(pull: dict, repo: Union[Repo, PlatformClient]) -> tuple[str, str]:
    """
    Get patch and test patch from PR

    Args:
        pull (dict): PR dictionary object from GitHub/GitLab
        repo: Repo object (deprecated) or PlatformClient instance
    Return:
        patch_change_str (str): gold patch
        patch_test_str (str): test patch
    """
    patch = requests.get(pull["diff_url"]).text
    patch_test = ""
    patch_fix = ""
    for hunk in PatchSet(patch):
        if any(
            test_word in hunk.path for test_word in ["test", "tests", "e2e", "testing"]
        ):
            patch_test += str(hunk)
        else:
            patch_fix += str(hunk)
    return patch_fix, patch_test


### MARK: Repo Specific Parsing Functions ###
def extract_problem_statement_and_hints_django(
    pull: dict, repo: Repo
) -> tuple[str, list[str]]:
    """
    Get problem statement and hints from issues associated with a pull request

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
    Return:
        text (str): problem statement
        hints (str): hints
    """
    text = ""
    all_hints_text = list()
    for issue_number in pull["resolved_issues"]:
        url = f"https://code.djangoproject.com/ticket/{issue_number}"
        resp = requests.get(url)
        if resp.status_code != 200:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")

        # Get problem statement (title + body)
        issue_desc = soup.find("div", {"id": "ticket"})
        title = issue_desc.find("h1", class_="searchable").get_text()
        title = re.sub(r"\s+", " ", title).strip()
        body = issue_desc.find("div", class_="description").get_text()
        body = re.sub(r"\n+", "\n", body)
        body = re.sub(r"    ", "\t", body)
        body = re.sub(r"[ ]{2,}", " ", body).strip()
        text += f"{title}\n{body}\n"

        # Get time of first commit in PR
        commits = repo.get_all_loop(
            repo.api.pulls.list_commits, pull_number=pull["number"], quiet=True
        )
        commits = list(commits)
        if len(commits) == 0:
            continue
        commit_time = commits[0].commit.author.date
        commit_time = time.mktime(time.strptime(commit_time, "%Y-%m-%dT%H:%M:%SZ"))

        # Get all comments before first commit
        comments_html = soup.find("div", {"id": "changelog"})
        div_blocks = comments_html.find_all("div", class_="change")
        # Loop through each div block
        for div_block in div_blocks:
            # Find the comment text and timestamp
            comment_resp = div_block.find("div", class_="comment")
            timestamp_resp = div_block.find("a", class_="timeline")
            if comment_resp is None or timestamp_resp is None:
                continue

            comment_text = re.sub(r"\s+", " ", comment_resp.text).strip()
            timestamp = timestamp_resp["title"]
            if timestamp.startswith("See timeline at "):
                timestamp = timestamp[len("See timeline at ") :]
            if "/" in timestamp:
                timestamp = time.mktime(time.strptime(timestamp, "%m/%d/%y %H:%M:%S"))
            elif "," in timestamp:
                timestamp = time.mktime(
                    time.strptime(timestamp, "%b %d, %Y, %I:%M:%S %p")
                )
            else:
                raise ValueError(f"Timestamp format not recognized: {timestamp}")

            # Append the comment and timestamp as a tuple to the comments list
            if timestamp < commit_time:
                all_hints_text.append((comment_text, timestamp))

    return text, all_hints_text
