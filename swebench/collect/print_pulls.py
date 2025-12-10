#!/usr/bin/env python3

"""Given a repository identifier, this script writes the raw information for all the repo's PRs/MRs to a single `.jsonl` file.

Supports both GitHub and GitLab repositories.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastcore.xtras import obj2dict

from swebench.collect.platform_client import detect_platform
from swebench.collect.utils import create_client

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def log_all_pulls(
    client,
    output: str,
    max_pulls: int = None,
    cutoff_date: str = None,
) -> None:
    """
    Iterate over all pull requests/merge requests in a repository and log them to a file

    Args:
        client: PlatformClient instance (GitHub or GitLab)
        output (str): output file name
        max_pulls (int): maximum number of PRs/MRs to fetch
        cutoff_date (str): cutoff date in YYYYMMDD format
    """
    cutoff_date = (
        datetime.strptime(cutoff_date, "%Y%m%d").strftime("%Y-%m-%dT%H:%M:%SZ")
        if cutoff_date is not None
        else None
    )

    with open(output, "w") as file:
        for i_pull, pull in enumerate(client.get_all_pulls()):
            # Extract resolved issues
            if isinstance(pull, dict):
                # New PlatformClient returns dicts
                pull["resolved_issues"] = client.extract_resolved_issues(pull)
                print(json.dumps(pull), end="\n", flush=True, file=file)
                created_at = pull.get("created_at", "")
            else:
                # Old-style object (backward compatibility)
                setattr(pull, "resolved_issues", client.extract_resolved_issues(pull))
                print(json.dumps(obj2dict(pull)), end="\n", flush=True, file=file)
                created_at = pull.created_at if hasattr(pull, "created_at") else ""

            if max_pulls is not None and i_pull >= max_pulls:
                break
            if cutoff_date is not None and created_at < cutoff_date:
                break


def log_pulls_from_file(
    pulls_file: str,
    output: str,
    token: Optional[str] = None,
    platform: Optional[str] = None,
    gitlab_url: str = "https://gitlab.com",
) -> None:
    """
    Fetch multiple PRs/MRs from a JSON file containing URLs.

    Expected JSON format:
    {
      "include": [
        {
          "mr": "https://gitlab.com/owner/repo/-/merge_requests/123",
          "issue": "https://gitlab.com/owner/repo/-/issues/456"
        },
        ...
      ]
    }

    Or simple list format:
    {
      "mrs": [123, 456, 789]
    }

    Args:
        pulls_file (str): Path to JSON file with MR/PR URLs
        output (str): output file name
        token (str, optional): API token
        platform (str, optional): platform type
        gitlab_url (str, optional): GitLab instance URL
    """
    import re

    from swebench.collect.utils import create_client

    # Read the JSON file
    with open(pulls_file) as f:
        data = json.load(f)

    # Parse entries
    entries = []
    if "include" in data:
        # Format with URLs
        for item in data["include"]:
            mr_url = item.get("mr", "")
            issue_url = item.get("issue", "")

            # Extract project path and MR number from URL
            # Pattern: https://gitlab.com/owner/repo/-/merge_requests/123
            mr_match = re.search(r"https?://[^/]+/(.+?)/-/merge_requests/(\d+)", mr_url)
            if not mr_match:
                logger.warning(f"Could not parse MR URL: {mr_url}")
                continue

            project_path = mr_match.group(1)
            mr_number = int(mr_match.group(2))

            # Extract issue number and project path if provided
            issue_references = []
            if issue_url:
                # Parse: https://gitlab.com/{project_path}/-/issues/{number}
                # Or: https://gitlab.com/{project_path}/-/work_items/{number}
                issue_match = re.search(
                    r"https?://[^/]+/(.+?)/-/(?:work_items|issues)/(\d+)", issue_url
                )
                if issue_match:
                    issue_project = issue_match.group(1)
                    issue_number = issue_match.group(2)
                    issue_references.append(
                        {
                            "number": issue_number,
                            "project": issue_project,  # May be different from MR project
                        }
                    )

            entries.append(
                {
                    "project": project_path,
                    "mr": mr_number,
                    "issues": issue_references,
                }
            )
    elif "mrs" in data:
        # Simple format with just numbers (requires repo_name from CLI)
        logger.error("Simple 'mrs' format requires --repo_name to be specified")
        return

    if not entries:
        logger.error(f"No valid MR entries found in {pulls_file}")
        return

    logger.info(f"Found {len(entries)} MRs to collect from {pulls_file}")

    # Group by project to reuse clients
    from collections import defaultdict

    by_project = defaultdict(list)
    for entry in entries:
        by_project[entry["project"]].append(entry)

    # Collect all MRs
    with open(output, "w") as file:
        for project_path, project_entries in by_project.items():
            logger.info(f"Collecting {len(project_entries)} MRs from {project_path}")

            # Detect platform
            detected_platform = platform if platform else detect_platform(project_path)

            # Get token
            current_token = token
            if current_token is None:
                if detected_platform == "gitlab":
                    current_token = os.environ.get("GITLAB_TOKEN")
                else:
                    current_token = os.environ.get("GITHUB_TOKEN")

            # Create client
            try:
                client = create_client(
                    project_path,
                    token=current_token,
                    platform=detected_platform,
                    gitlab_url=gitlab_url,
                )
                logger.info(f"Created {type(client).__name__} for {project_path}")
            except Exception as e:
                logger.error(f"Failed to create client for {project_path}: {e}")
                continue

            # Fetch each MR
            for entry in project_entries:
                mr_number = entry["mr"]
                logger.info(f"Fetching MR #{mr_number} from {project_path}")

                try:
                    pull = client.get_pull(mr_number)
                    if pull is None:
                        logger.error(f"MR #{mr_number} not found")
                        continue

                    # Extract resolved issues or use provided ones
                    auto_resolved = client.extract_resolved_issues(pull)
                    if entry["issues"]:
                        # Use provided issue references (with project info for cross-project issues)
                        pull["issue_references"] = entry[
                            "issues"
                        ]  # Full metadata: [{number, project}, ...]
                        pull["resolved_issues"] = [
                            issue["number"] for issue in entry["issues"]
                        ]  # Just numbers for compatibility
                        logger.info(
                            f"Using provided issues: {pull['resolved_issues']} (auto-detected: {auto_resolved})"
                        )
                    else:
                        pull["resolved_issues"] = auto_resolved
                        pull["issue_references"] = [
                            {"number": num, "project": project_path}
                            for num in auto_resolved
                        ]
                        logger.info(f"Auto-detected issues: {auto_resolved}")

                    # Write to file
                    print(json.dumps(pull), end="\n", flush=True, file=file)
                    logger.info(f"✅ MR #{mr_number} saved")

                except Exception as e:
                    logger.error(f"Failed to fetch MR #{mr_number}: {e}")
                    continue

    logger.info(f"Completed: {len(entries)} MRs saved to {output}")


def log_single_pull(
    client,
    pull_number: int,
    output: str,
    repo_identifier: str,
) -> None:
    """
    Get a single pull request/merge request from a repository and log it to a file

    Args:
        client: PlatformClient instance (GitHub or GitLab)
        pull_number (int): pull request/merge request number
        output (str): output file name
        repo_identifier (str): repository identifier for logging
    """
    logger.info(f"Fetching PR/MR #{pull_number} from {repo_identifier}")

    # Get the pull request using the platform API
    pull = client.get_pull(pull_number)

    if pull is None:
        logger.error(f"PR/MR #{pull_number} not found in {repo_identifier}")
        return

    # Extract resolved issues
    if isinstance(pull, dict):
        pull["resolved_issues"] = client.extract_resolved_issues(pull)
        resolved = pull["resolved_issues"]
    else:
        setattr(pull, "resolved_issues", client.extract_resolved_issues(pull))
        resolved = pull.resolved_issues

    # Log the pull request to a file
    with open(output, "w") as file:
        if isinstance(pull, dict):
            print(json.dumps(pull), end="\n", flush=True, file=file)
        else:
            print(json.dumps(obj2dict(pull)), end="\n", flush=True, file=file)

    logger.info(f"PR/MR #{pull_number} saved to {output}")
    logger.info(f"Resolved issues: {resolved}")


def main(
    repo_name: Optional[str] = None,
    output: str = None,
    token: Optional[str] = None,
    max_pulls: int = None,
    cutoff_date: str = None,
    pull_number: int = None,
    pull_numbers_file: Optional[str] = None,
    platform: Optional[str] = None,
    gitlab_url: str = "https://gitlab.com",
):
    """
    Logic for logging all pull requests/merge requests in a repository

    Args:
        repo_name (str, optional): repository identifier (e.g., "owner/repo" or "group/project")
        output (str): output file name
        token (str, optional): API token (GitHub or GitLab)
        max_pulls (int, optional): maximum number of pulls/MRs to log
        cutoff_date (str, optional): cutoff date for PRs/MRs to consider (YYYYMMDD)
        pull_number (int, optional): specific pull request/merge request number to log
        pull_numbers_file (str, optional): JSON file with list of MRs to fetch
        platform (str, optional): platform ('github' or 'gitlab'). Auto-detects if not specified.
        gitlab_url (str, optional): GitLab instance URL (default: https://gitlab.com)
    """
    # Handle batch file input
    if pull_numbers_file:
        logger.info(f"Using MR list from file: {pull_numbers_file}")
        log_pulls_from_file(
            pulls_file=pull_numbers_file,
            output=output,
            token=token,
            platform=platform,
            gitlab_url=gitlab_url,
        )
        return

    # Validate required args for non-file modes
    if not repo_name:
        logger.error("repo_name is required when not using --pull_numbers_file")
        return
    # Determine platform if not specified
    if platform is None:
        platform = detect_platform(repo_name)
        logger.info(f"Auto-detected platform: {platform}")

    # Get token from environment if not provided
    if token is None:
        if platform == "gitlab":
            token = os.environ.get("GITLAB_TOKEN")
            if token is None:
                logger.warning(
                    "No GITLAB_TOKEN found. API requests may be rate-limited."
                )
        else:
            token = os.environ.get("GITHUB_TOKEN")
            if token is None:
                logger.warning(
                    "No GITHUB_TOKEN found. API requests may be rate-limited."
                )

    # Create platform client
    client = create_client(
        repo_name, token=token, platform=platform, gitlab_url=gitlab_url
    )
    logger.info(f"Created {type(client).__name__} for {repo_name}")

    # Fetch PRs/MRs
    if pull_number is not None:
        log_single_pull(client, pull_number, output, repo_name)
    else:
        log_all_pulls(client, output, max_pulls=max_pulls, cutoff_date=cutoff_date)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repo_name",
        type=str,
        nargs="?",
        help="Repository identifier (e.g., 'owner/repo' for GitHub or 'group/project' for GitLab). Not required when using --pull_numbers_file.",
    )
    parser.add_argument("output", type=str, help="Output file name")
    parser.add_argument(
        "--token",
        type=str,
        help="API token (GitHub or GitLab). Falls back to GITHUB_TOKEN or GITLAB_TOKEN env var.",
    )
    parser.add_argument(
        "--max_pulls",
        type=int,
        help="Maximum number of pull requests/merge requests to log",
        default=None,
    )
    parser.add_argument(
        "--cutoff_date",
        type=str,
        help="Cutoff date for PRs/MRs to consider in format YYYYMMDD",
        default=None,
    )
    parser.add_argument(
        "--pull_number",
        type=int,
        help="Specific pull request/merge request number to log",
        default=None,
    )
    parser.add_argument(
        "--pull_numbers_file",
        type=str,
        help="JSON file containing list of MRs to fetch (format: {'include': [{'mr': 'url', 'issue': 'url'}, ...]})",
        default=None,
    )
    parser.add_argument(
        "--platform",
        type=str,
        choices=["github", "gitlab"],
        help="Platform type (github or gitlab). Auto-detects if not specified.",
        default=None,
    )
    parser.add_argument(
        "--gitlab_url",
        type=str,
        help="GitLab instance URL (default: https://gitlab.com)",
        default="https://gitlab.com",
    )
    args = parser.parse_args()
    main(**vars(args))
