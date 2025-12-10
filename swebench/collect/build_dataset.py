#!/usr/bin/env python3

"""Build task instances from pull request/merge request data.

Supports both GitHub and GitLab repositories.
"""

import argparse
import json
import logging
import os
from typing import Optional

from swebench.collect.platform_client import detect_platform
from swebench.collect.utils import (
    create_client,
    extract_patches,
    extract_problem_statement_and_hints,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_repo_name(pull: dict) -> str:
    """
    Extract repository name from pull request data (platform-agnostic).

    Args:
        pull: PR/MR dictionary
    Returns:
        Repository name in format "owner/repo" or "group/project"
    """
    # GitHub format: pull["base"]["repo"]["full_name"]
    if "base" in pull and isinstance(pull["base"], dict):
        if "repo" in pull["base"] and isinstance(pull["base"]["repo"], dict):
            return pull["base"]["repo"]["full_name"]

    # GitLab normalized format or fallback: pull["repo"]
    # Might not exist in all cases, so provide sensible error
    if "repo" in pull:
        return pull["repo"]

    raise ValueError(
        f"Cannot extract repo name from pull request data: {list(pull.keys())}"
    )


def get_base_commit(pull: dict) -> str:
    """
    Extract base commit SHA from pull request data (platform-agnostic).

    Args:
        pull: PR/MR dictionary
    Returns:
        Base commit SHA
    """
    # GitHub format: pull["base"]["sha"]
    if "base" in pull and isinstance(pull["base"], dict):
        if "sha" in pull["base"]:
            return pull["base"]["sha"]

    # GitLab or alternative format: might be at top level
    if "base_commit" in pull:
        return pull["base_commit"]

    raise ValueError(
        f"Cannot extract base commit from pull request data: {list(pull.keys())}"
    )


def create_instance(client, pull: dict) -> dict:
    """
    Create a single task instance from a pull request/merge request.

    Args:
        client: PlatformClient instance (GitHub or GitLab)
        pull: PR/MR dictionary

    Returns:
        Task instance dictionary with fields:
        - repo (str): repository identifier
        - pull_number (int): PR/MR number
        - base_commit (str): base commit SHA
        - patch (str): solution patch
        - test_patch (str): test suite patch
        - problem_statement (str): issue description
        - hints_text (str): hints from comments
        - created_at (str): creation timestamp
        - instance_id (str): unique identifier
    """
    # Extract data in platform-agnostic way
    repo_name = get_repo_name(pull)
    base_commit = get_base_commit(pull)

    # Extract patches and problem statement
    patch, test_patch = extract_patches(pull, client)
    problem_statement, hints = extract_problem_statement_and_hints(pull, client)

    # Create instance ID (replace / with __ for all platforms, including nested GitLab groups)
    instance_id = (repo_name + "-" + str(pull["number"])).replace("/", "__")

    return {
        "repo": repo_name,
        "pull_number": pull["number"],
        "instance_id": instance_id,
        "issue_numbers": pull.get("resolved_issues", []),
        "base_commit": base_commit,
        "patch": patch,
        "test_patch": test_patch,
        "problem_statement": problem_statement,
        "hints_text": hints,
        "created_at": pull.get("created_at", ""),
    }


def is_valid_pull(pull: dict) -> bool:
    """
    Check whether PR has an associated issue and is merged

    Args:
        pull (dict): pull request object
    Returns:
        bool: whether PR is valid
    """
    if pull["merged_at"] is None:
        return False
    if "resolved_issues" not in pull or len(pull["resolved_issues"]) < 1:
        return False
    return True


def is_valid_instance(instance: dict) -> bool:
    """
    Check whether task instance has all required fields for task instance creation

    Args:
        instance (dict): task instance object
    Returns:
        bool: whether task instance is valid
    """
    if instance["patch"] is None or instance["patch"] == "":
        return False
    if instance["problem_statement"] is None or instance["problem_statement"] == "":
        return False
    return True


def has_test_patch(instance: dict) -> bool:
    """
    Check whether task instance has a test suite

    Args:
        instance (dict): task instance object
    Returns:
        bool: whether task instance has a test suite
    """
    if instance["test_patch"] is None or instance["test_patch"].strip() == "":
        return False
    return True


def main(
    pr_file: str,
    output: str,
    token: Optional[str] = None,
    platform: Optional[str] = None,
    gitlab_url: str = "https://gitlab.com",
):
    """
    Main thread for creating task instances from pull requests/merge requests

    Args:
        pr_file (str): path to pull request/merge request JSONL file
        output (str): output file name
        token (str, optional): API token (GitHub or GitLab)
        platform (str, optional): platform type ('github' or 'gitlab'). Auto-detects if not provided.
        gitlab_url (str): GitLab instance URL (default: https://gitlab.com)
    """

    def load_client(repo_name):
        """Create a platform client for a given repository"""
        # Auto-detect platform if not specified
        detected_platform = platform if platform else detect_platform(repo_name)

        # Get token from environment if not provided
        current_token = token
        if current_token is None:
            if detected_platform == "gitlab":
                current_token = os.environ.get("GITLAB_TOKEN")
            else:
                current_token = os.environ.get("GITHUB_TOKEN")

        # Create and return client
        return create_client(
            repo_name,
            token=current_token,
            platform=detected_platform,
            gitlab_url=gitlab_url,
        )

    clients = dict()  # Cache of platform clients by repo name
    completed = 0
    with_tests = 0
    total_instances = 0
    all_output_path = output + ".all"
    seen_prs = set()

    # Continue where we left off if output file already exists
    if os.path.exists(all_output_path):
        with open(all_output_path) as f:
            for line in f:
                pr = json.loads(line)
                if "instance_id" not in pr:
                    pr["instance_id"] = (
                        pr["repo"] + "-" + str(pr["pull_number"])
                    ).replace("/", "__")
                instance_id = pr["instance_id"]
                seen_prs.add(instance_id)
                if is_valid_instance(pr):
                    completed += 1
                    if has_test_patch(pr):
                        with_tests += 1
    logger.info(
        f"Will skip {len(seen_prs)} pull requests that have already been inspected"
    )

    # Write to .all file for all PRs
    write_mode_all = "w" if not os.path.exists(all_output_path) else "a"
    with open(all_output_path, write_mode_all) as all_output_file:
        # Write to output file for PRs with test suites
        write_mode = "w" if not os.path.exists(output) else "a"
        with open(output, write_mode) as output_file:
            for ix, line in enumerate(open(pr_file)):
                total_instances += 1
                pull = json.loads(line)

                # Extract repo name using platform-agnostic helper
                try:
                    repo_name = get_repo_name(pull)
                except ValueError as e:
                    logger.warning(f"Skipping PR due to error: {e}")
                    continue

                if ix % 100 == 0:
                    logger.info(
                        f"[{repo_name}] (Up to {ix} checked) "
                        f"{completed} valid, {with_tests} with tests."
                    )

                # Construct instance ID
                instance_id = (repo_name + "-" + str(pull["number"])).replace("/", "__")

                if instance_id in seen_prs:
                    seen_prs -= {instance_id}
                    continue

                if not is_valid_pull(pull):
                    # Throw out invalid PRs
                    continue

                # Create platform client (cached)
                if repo_name not in clients:
                    try:
                        clients[repo_name] = load_client(repo_name)
                        logger.info(
                            f"Created {type(clients[repo_name]).__name__} for {repo_name}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to create client for {repo_name}: {e}")
                        continue

                client = clients[repo_name]

                # Create task instance
                try:
                    instance = create_instance(client, pull)
                except Exception as e:
                    logger.error(
                        f"Failed to create instance for {repo_name} PR #{pull['number']}: {e}"
                    )
                    continue

                if is_valid_instance(instance):
                    # If valid, write to .all output file
                    print(
                        json.dumps(instance), end="\n", flush=True, file=all_output_file
                    )
                    completed += 1
                    if has_test_patch(instance):
                        # If has test suite, write to output file
                        print(
                            json.dumps(instance), end="\n", flush=True, file=output_file
                        )
                        with_tests += 1

    logger.info(
        f"[{', '.join(clients.keys())}] Total instances: {total_instances}, completed: {completed}, with tests: {with_tests}"
    )
    logger.info(
        f"[{', '.join(clients.keys())}] Skipped {len(seen_prs)} pull requests that have already been inspected"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pr_file",
        type=str,
        help="Path to pull request/merge request JSONL file (from print_pulls.py)",
    )
    parser.add_argument("output", type=str, help="Output file name")
    parser.add_argument(
        "--token",
        type=str,
        help="API token (GitHub or GitLab). Falls back to GITHUB_TOKEN or GITLAB_TOKEN env var.",
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
