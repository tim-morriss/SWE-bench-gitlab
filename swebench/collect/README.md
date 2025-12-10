# Data Collection

> [!NOTE]
> If you interested in creating tasks for training models to solve software engineering tasks,
> check
> out [SWE-smith](https://swesmith.com/) ([Code](https://github.com/SWE-bench/SWE-smith), [Paper](https://swesmith.com/assets/paper.pdf)).
>
> SWE-smith is a toolkit for creating execution environments and SWE-bench style task instances at scale.
>
> It is designed to be highly compatible with [SWE-agent](https://github.com/SWE-agent/SWE-agent),
> to generate training data, and SWE-bench for evaluation.

This folder includes the code for the first two parts of the benchmark construction procedure as described in the paper,
specifically 1. Repo selection and data scraping, and 2. Attribute-based filtering.

We include a comprehensive [tutorial](docs/guides/collection.md) that describes the end-to-end procedure for collecting
evaluation task instances from PyPI repositories.

> **Note**: This fork now supports **both GitHub and GitLab** repositories! You can collect task instances from
> GitLab.com merge requests (MRs) and self-hosted GitLab instances.

<img src="../../docs/assets/figures/collection.png">

## GitLab Support 🦊

This collection pipeline now supports GitLab merge requests in addition to GitHub pull requests, with full support for:

- ✅ GitLab.com and self-hosted GitLab instances
- ✅ Nested group structures (e.g., `group/subgroup/project`)
- ✅ Cross-project issue references
- ✅ Mixed GitHub/GitLab datasets
- ✅ GitLab-specific issue resolution keywords (Closes, Fixes, Resolves, Implements, Relates, etc.)

### Quick Start - GitLab

#### Prerequisites

Set up your GitLab Personal Access Token with `read_api` scope:

```bash
export GITLAB_TOKEN="your_token_here"
# Or use comma-separated tokens for parallel processing:
export GITLAB_TOKENS="token1,token2,token3"
```

#### Collect a Single MR

```bash
poetry run python -m swebench.collect.print_pulls \
    gitlab-org/gitlab \
    gitlab_mr.jsonl \
    --pull_number 12345 \
    --token $GITLAB_TOKEN
```

#### Collect Multiple MRs from a JSON File

Create a JSON file with MR URLs and their associated issues:

```json
{
  "include": [
    {
      "mr": "https://gitlab.com/owner/project/-/merge_requests/123",
      "issue": "https://gitlab.com/owner/project/-/issues/456"
    },
    {
      "mr": "https://gitlab.com/owner/project/-/merge_requests/789",
      "issue": "https://gitlab.com/other-owner/other-project/-/issues/101"
    }
  ]
}
```

Then run:

```bash
poetry run python -m swebench.collect.print_pulls \
    output \
    batch_mrs.jsonl \
    --pull_numbers_file mrs.json \
    --token $GITLAB_TOKEN
```

#### Build Task Instances

```bash
poetry run python -m swebench.collect.build_dataset \
    batch_mrs.jsonl \
    task_instances.jsonl \
    --token $GITLAB_TOKEN
```

#### Collect All MRs from a Repository

```bash
poetry run python -m swebench.collect.print_pulls \
    gitlab-org/gitlab \
    gitlab_mrs.jsonl \
    --max_pulls 100 \
    --token $GITLAB_TOKEN
```

#### Mixed Platform Collection

```bash
poetry run python -m swebench.collect.get_tasks_pipeline \
    --repos \
        django/django \
        gitlab-org/gitlab \
        python/cpython \
    --path_prs ./prs \
    --path_tasks ./tasks
# Platform auto-detected per repository
```

### GitLab-Specific Features

**Cross-Project Issue References**: The pipeline automatically handles issue references across different projects:

```json
{
  "mr": "https://gitlab.com/project-a/-/merge_requests/100",
  "issue": "https://gitlab.com/project-b/-/issues/200"
}
```

**Issue Resolution Keywords**: Extended support for GitLab keywords:

- Auto-closing: `Closes`, `Fixes`, `Resolves`, `Implements`
- Referencing: `Relates`, `Addresses`, `References`, `See`

**Self-Hosted GitLab**:

```bash
export GITLAB_URL="https://gitlab.example.com"
poetry run python -m swebench.collect.print_pulls \
    myorg/myproject \
    mrs.jsonl \
    --gitlab_url $GITLAB_URL \
    --token $GITLAB_TOKEN
```

## Collection Procedure

To run collection on your own repositories, run the `run_get_tasks_pipeline.sh` script. Given a repository or list of
repositories (formatted as `owner/name` for GitHub or `group/project` for GitLab), for each repository this command will
generate...

* `<repo>-prs.jsonl` file containing the metadata for every pull request/merge request from the repository.
    * GitHub: [Pull Request metadata](https://docs.github.com/rest/reference/pulls#list-pull-requests)
    * GitLab: [Merge Request metadata](https://docs.gitlab.com/ee/api/merge_requests.html) (normalized to match GitHub
      format)
* `<repo>-task-instances.jsonl.all` file containing all *valid* task instances (has associated issues + gold patch).
    * This file's values can be used for fine tuning purposes.
    * Works for both GitHub PRs and GitLab MRs
* `<repo>-task-instances.jsonl` file containing *valid* task instances that also has associated *tests*.
    * This file's values are candidate task instances. Once validated, they can be used for evaluation purposes.
    * The `.json.all` includes these task instances as well.

**Note**: Repository names with `/` characters (including nested GitLab groups) are converted to `__` in filenames. For
example:

- GitHub: `owner/repo` → `owner__repo-prs.jsonl`
- GitLab: `group/subgroup/project` → `group__subgroup__project-prs.jsonl`

## Directory Overview

In this section, we briefly describe each of the files in this directory and its usage details.

**🧐 GitHub Repository Selection**

* `get_top_pypi.py`
    * Purpose: Retrieves the PyPI URL, GitHub URL, # of ⭐, and # of Issues + PRs for
      the [top 5000](https://hugovk.github.io/top-pypi-packages/) most downloaded PyPI packages.
    * Usage: `python get_top_pypi.py`

**⛏️ GitHub & GitLab Data Collection**

* `print_pulls.py`
    * Purpose: Given the `<owner/name>` of a GitHub repo or GitLab project, this script writes the raw information for
      all the repo's PRs/MRs to a single `.jsonl` file
    * Platform Support: **GitHub** and **GitLab** (auto-detected or specify with `--platform`)
    * Usage: `python print_pulls.py <repo name> <path to PRs .jsonl file> --token <Token>`
    * GitLab Usage: `python print_pulls.py gitlab-org/gitlab output.jsonl --token $GITLAB_TOKEN`
    * Batch Mode: `python print_pulls.py output output.jsonl --pull_numbers_file mrs.json --token $GITLAB_TOKEN`
* `build_dataset.py`
    * Purpose: Given the path to a PRs/MRs `.jsonl` file generated by `print_pulls.py`, this script attempts to convert
      each PR/MR to a task instance. It creates a `jsonl.all` file for any PRs/MRs with an issue and a `.jsonl` file for
      any PRs/MRs with both an issue and modifications to that repository's tests.
    * Platform Support: **GitHub** and **GitLab** (auto-detected)
    * Cross-Project Issues: **GitLab** MRs can reference issues from different projects
    * Usage: `python build_dataset.py <path to PRs .jsonl file> <path to output .jsonl file> --token <Token>`
* `get_tasks_pipeline.py`
    * Purpose: Automates invocation of the repo → task instance construction pipeline (`print_pulls.py` +
      `build_dataset.py`) for multiple repositories
    * Platform Support: **Mixed GitHub and GitLab** repositories in a single run
    * Usage: `./run_get_tasks_pipeline` (Check file for arguments)
* `platform_client.py`
    * Purpose: Abstract interface for platform-agnostic API interactions
    * Implementations: `GitHubClient` (uses `ghapi`), `GitLabClient` (uses `python-gitlab`)
* `gitlab_client.py`
    * Purpose: GitLab-specific API client implementation
    * Features: Nested groups, cross-project issues, MR normalization, extended issue keywords

**🎵 Fine Tuning Dataset Construction**

* `build_dataset_ft.py`
    * Purpose: Given the path to a collection of `.jsonl.all` files generated by `build_dataset.py`, this is a simple
      script to combine all such files into a single `.jsonl` that can be used to construct a instruction tuning dataset
      based on [problem statement + original code, code Δ] pairs.
    * Usage: `./run_build_dataset_ft` (Check file for arguments)

**🪞 Mirroring Repositories**

* `make_repo.sh`
    * Purpose: A script for creating
      a [mirror repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/duplicating-a-repository)
      of an existing repository on GitHub. Examples available under
      the [swe-bench organization](https://github.com/orgs/swe-bench/repositories).
    * Usage: `python call_make_repo.py` (Check file for arguments)

**🧹 Clean Up**

* `delete_gh_workflows.py`
    * Purpose: Recurring workflows from mirror repositories can clog up your inbox for the email account associated with
      your GitHub token. Given a repo URL, this will automate removing the `.github/workflows` folder from all branches
      of a repository.
    * Usage: `python delete_gh_workflows.py <repo URL>`
* `remove_envs.py`
    * Purpose: SWE Bench's evaluation + validation harnesses rely on the creation of multiple virtual environments with
      conda to speed up benchmark evaluation. Use these script to parallelize conda environment removal for environments
      named with the same prefix.
    * Usage: `python remove_envs.py <prefix> --conda_path <path to conda installation>`

## Known Limitations & Considerations

### GitLab API Limitations

**Issue Comments (Notes API)**: The GitLab Notes API requires authentication even for public
projects ([GitLab Issue #61001](https://gitlab.com/gitlab-org/gitlab-foss/-/issues/61001)). This is a known limitation
compared to GitHub. The pipeline handles this gracefully:

- Issue content (problem statements) are fetched successfully
- Comments (hints) are skipped with a warning if authentication fails
- Task instances are still created (comments are optional)

**Workaround**: Use a valid `GITLAB_TOKEN` with `read_api` scope to access comments.

### Cross-Project Issue References

When a GitLab MR references an issue from a different project:

1. The pipeline automatically creates a separate API client for that project
2. Requires the issue to be publicly accessible or your token to have access
3. Issue metadata is stored in the `issue_references` field with full project path

### Platform Detection

The pipeline auto-detects platforms based on:

- Repository string format (nested paths → GitLab)
- Presence of "gitlab.com" in URLs
- Can be overridden with `--platform github` or `--platform gitlab`

### Rate Limits

- **GitHub**: 5,000 requests/hour (authenticated)
- **GitLab**: 2,000 requests/hour (authenticated), 300/hour (unauthenticated)
- Use `GITHUB_TOKENS` or `GITLAB_TOKENS` (comma-separated) for parallel processing
