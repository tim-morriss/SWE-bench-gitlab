#!/usr/bin/env python3

"""Script to collect pull requests/merge requests and convert them to candidate task instances.

Supports both GitHub and GitLab repositories.
"""

import argparse
import os
import traceback
from multiprocessing import Pool

from dotenv import load_dotenv

from swebench.collect.build_dataset import main as build_dataset
from swebench.collect.platform_client import detect_platform
from swebench.collect.print_pulls import main as print_pulls

load_dotenv()


def split_instances(input_list: list, n: int) -> list:
    """
    Split a list into n approximately equal length sublists

    Args:
        input_list (list): List to split
        n (int): Number of sublists to split into
    Returns:
        result (list): List of sublists
    """
    avg_length = len(input_list) // n
    remainder = len(input_list) % n
    result, start = [], 0

    for i in range(n):
        length = avg_length + 1 if i < remainder else avg_length
        sublist = input_list[start : start + length]
        result.append(sublist)
        start += length

    return result


def construct_data_files(data: dict):
    """
    Logic for collecting PR/MR data and converting to task instances

    Args:
        data (dict): Dictionary containing the following keys:
            repos (list): List of repositories to retrieve data for
            path_prs (str): Path to save PR/MR data files to
            path_tasks (str): Path to save task instance data files to
            github_token (str): GitHub token to use for API requests
            gitlab_token (str): GitLab token to use for API requests
            gitlab_url (str): GitLab instance URL
            max_pulls (int): Maximum number of PRs/MRs to fetch
            cutoff_date (str): Cutoff date for PRs/MRs
    """
    repos = data["repos"]
    path_prs = data["path_prs"]
    path_tasks = data["path_tasks"]
    max_pulls = data["max_pulls"]
    cutoff_date = data["cutoff_date"]
    github_token = data["github_token"]
    gitlab_token = data["gitlab_token"]
    gitlab_url = data["gitlab_url"]

    for repo in repos:
        repo = repo.strip(",").strip()

        # Detect platform for this repo
        platform = detect_platform(repo)
        print(f"📍 Detected platform for {repo}: {platform}")

        # Get appropriate token
        token = gitlab_token if platform == "gitlab" else github_token

        # Generate safe filename (replace / with __)
        repo_name_safe = repo.replace("/", "__")

        try:
            # Path for PR/MR data
            path_pr = os.path.join(path_prs, f"{repo_name_safe}-prs.jsonl")
            if cutoff_date:
                path_pr = path_pr.replace(".jsonl", f"-{cutoff_date}.jsonl")

            # Collect PR/MR data
            if not os.path.exists(path_pr):
                print(f"Pull request/MR data for {repo} not found, creating...")
                print_pulls(
                    repo_name=repo,
                    output=path_pr,
                    token=token,
                    max_pulls=max_pulls,
                    cutoff_date=cutoff_date,
                    platform=platform,
                    gitlab_url=gitlab_url,
                )
                print(f"✅ Successfully saved PR/MR data for {repo} to {path_pr}")
            else:
                print(
                    f"📁 Pull request/MR data for {repo} already exists at {path_pr}, skipping..."
                )

            # Path for task instances
            path_task = os.path.join(
                path_tasks, f"{repo_name_safe}-task-instances.jsonl"
            )

            # Build task instances
            if not os.path.exists(path_task):
                print(f"Task instance data for {repo} not found, creating...")
                build_dataset(
                    pr_file=path_pr,
                    output=path_task,
                    token=token,
                    platform=platform,
                    gitlab_url=gitlab_url,
                )
                print(
                    f"✅ Successfully saved task instance data for {repo} to {path_task}"
                )
            else:
                print(
                    f"📁 Task instance data for {repo} already exists at {path_task}, skipping..."
                )
        except Exception as e:
            print("-" * 80)
            print(f"Something went wrong for {repo}, skipping: {e}")
            print("Here is the full traceback:")
            traceback.print_exc()
            print("-" * 80)


def main(
    repos: list,
    path_prs: str,
    path_tasks: str,
    max_pulls: int = None,
    cutoff_date: str = None,
    gitlab_url: str = "https://gitlab.com",
):
    """
    Spawns multiple threads for collecting PR/MR data from GitHub and/or GitLab

    Supports mixed repositories (both GitHub and GitLab). Platform is detected automatically
    for each repository.

    Args:
        repos (list): List of repositories (GitHub: owner/repo, GitLab: group/project)
        path_prs (str): Path to save PR/MR data files to
        path_tasks (str): Path to save task instance data files to
        max_pulls (int): Maximum number of PRs/MRs to fetch per repo
        cutoff_date (str): Cutoff date for PRs/MRs in format YYYYMMDD
        gitlab_url (str): GitLab instance URL (default: https://gitlab.com)
    """
    path_prs, path_tasks = os.path.abspath(path_prs), os.path.abspath(path_tasks)
    print(f"Will save PR/MR data to {path_prs}")
    print(f"Will save task instance data to {path_tasks}")
    print(f"Received following repos to create task instances for: {repos}")

    # Get GitHub tokens
    github_tokens = os.getenv("GITHUB_TOKENS")
    if not github_tokens:
        github_token = os.getenv("GITHUB_TOKEN")
        if github_token:
            github_tokens = github_token
            print("⚠️  Using single GITHUB_TOKEN (no parallelization for GitHub repos)")
        else:
            print(
                "⚠️  No GITHUB_TOKEN found. GitHub repos will fail without authentication."
            )
            github_tokens = ""

    # Get GitLab tokens
    gitlab_tokens = os.getenv("GITLAB_TOKENS")
    if not gitlab_tokens:
        gitlab_token = os.getenv("GITLAB_TOKEN")
        if gitlab_token:
            gitlab_tokens = gitlab_token
            print("⚠️  Using single GITLAB_TOKEN (no parallelization for GitLab repos)")
        else:
            print("⚠️  No GITLAB_TOKEN found. GitLab repos may be rate-limited.")
            gitlab_tokens = ""

    # Split into token lists for parallelization
    github_token_list = [t.strip() for t in github_tokens.split(",") if t.strip()]
    gitlab_token_list = [t.strip() for t in gitlab_tokens.split(",") if t.strip()]

    # Use max number of tokens for parallelization
    num_workers = max(len(github_token_list), len(gitlab_token_list), 1)

    # Pad token lists to match worker count
    while len(github_token_list) < num_workers:
        github_token_list.append(github_token_list[0] if github_token_list else "")
    while len(gitlab_token_list) < num_workers:
        gitlab_token_list.append(gitlab_token_list[0] if gitlab_token_list else "")

    # Split repos among workers
    data_task_lists = split_instances(repos, num_workers)

    # Create data for each worker
    data_pooled = [
        {
            "repos": repo_list,
            "path_prs": path_prs,
            "path_tasks": path_tasks,
            "max_pulls": max_pulls,
            "cutoff_date": cutoff_date,
            "github_token": gh_token,
            "gitlab_token": gl_token,
            "gitlab_url": gitlab_url,
        }
        for repo_list, gh_token, gl_token in zip(
            data_task_lists, github_token_list, gitlab_token_list
        )
    ]

    print(f"🚀 Starting {num_workers} worker(s) for parallel processing")

    # Run in parallel
    with Pool(num_workers) as p:
        p.map(construct_data_files, data_pooled)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repos",
        nargs="+",
        help="List of repositories (e.g., `sqlfluff/sqlfluff`) to create task instances for",
    )
    parser.add_argument(
        "--path_prs", type=str, help="Path to folder to save PR data files to"
    )
    parser.add_argument(
        "--path_tasks",
        type=str,
        help="Path to folder to save task instance data files to",
    )
    parser.add_argument(
        "--max_pulls", type=int, help="Maximum number of pulls to log", default=None
    )
    parser.add_argument(
        "--cutoff_date",
        type=str,
        help="Cutoff date for PRs to consider in format YYYYMMDD",
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
