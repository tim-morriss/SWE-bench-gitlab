# Contributing to SWE-bench

Thank you for your interest in contributing to SWE-bench! This document provides guidelines and instructions for contributing to the project.

## Development Setup

### Prerequisites

- Python 3.10 or higher
- [Poetry](https://python-poetry.org/) for dependency management
- Docker (for evaluation harness)

### Installation

1. **Fork and clone the repository:**
   ```bash
   git clone git@github.com:YOUR_USERNAME/SWE-bench.git
   cd SWE-bench
   ```

2. **Install dependencies with Poetry:**
   ```bash
   # Install Poetry if you haven't already
   curl -sSL https://install.python-poetry.org | python3 -

   # Install project dependencies
   poetry install --with test,docs
   ```

3. **Activate the virtual environment:**
   ```bash
   poetry shell
   ```

## Code Quality Standards

### Linting with Ruff

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and code formatting. **All code must pass Ruff checks before being merged.**

**Before committing, run:**
```bash
# Check for linting errors
poetry run ruff check .

# Auto-fix fixable issues
poetry run ruff check . --fix

# Format code
poetry run ruff format .
```

### Code Style Guidelines

- Follow [PEP 8](https://peps.python.org/pep-0008/) style guidelines
- Use explicit imports instead of wildcard imports (`from module import *`)
- Use `isinstance(x, type)` instead of `type(x) == type`
- Use `is None` and `is not None` instead of `== None` and `!= None`
- Prefer `def` functions over lambda expressions for anything non-trivial
- Use specific exception types instead of bare `except:` clauses
- Prefix intentionally unused variables with `_` (e.g., `_unused_var`)

### Type Hints

While not strictly required, type hints are encouraged for:
- Function parameters
- Function return types
- Public API methods

## Making Changes

### Branch Naming

Use descriptive branch names:
- `feature/add-gitlab-support`
- `fix/issue-123-timeout-error`
- `docs/update-readme`

### Commit Messages

Write clear, descriptive commit messages:
```
Add GitLab API client implementation

- Create platform_client.py with abstract interface
- Implement GitLabClient using python-gitlab library
- Add support for nested group structures
- Handle cross-project issue references

Fixes #123
```

### Pull Request Process

1. **Ensure all tests pass** (if applicable):
   ```bash
   poetry run pytest
   ```

2. **Run linting checks**:
   ```bash
   poetry run ruff check .
   ```

3. **Update documentation** if you've:
   - Added new features
   - Changed existing behavior
   - Modified public APIs

4. **Update CHANGELOG.md** with your changes under the `[Unreleased]` section

5. **Create a pull request** with:
   - Clear title describing the change
   - Description of what was changed and why
   - Reference to any related issues
   - Screenshots/examples if applicable

## Testing

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run specific test file
poetry run pytest tests/test_specific.py

# Run with coverage
poetry run pytest --cov=swebench
```

### Writing Tests

- Place tests in the `tests/` directory
- Name test files with `test_` prefix
- Use descriptive test function names
- Include docstrings explaining what the test validates

## Adding Dependencies

### Runtime Dependencies

```bash
# Add a new dependency
poetry add package-name

# Add with specific version constraint
poetry add "package-name>=1.0.0,<2.0.0"
```

### Development Dependencies

```bash
# Add a test dependency
poetry add --group test pytest-package

# Add a docs dependency
poetry add --group docs mkdocs-plugin
```

After adding dependencies:
1. Commit both `pyproject.toml` and `poetry.lock`
2. Document the new dependency in your PR

## Documentation

### Docstrings

Use Google-style docstrings:

```python
def process_instance(instance: dict, platform: str) -> dict:
    """
    Process a task instance for the given platform.

    Args:
        instance: Task instance dictionary containing repo, issue, etc.
        platform: Platform name ('github' or 'gitlab')

    Returns:
        Processed task instance with normalized fields

    Raises:
        ValueError: If platform is not supported
    """
    pass
```

### Updating Documentation

- Update README.md for user-facing changes
- Update docs/ for detailed guides
- Update CHANGELOG.md for all changes
- Add inline comments for complex logic

## GitLab Support Development

When working on GitLab-related features:

1. Use the platform abstraction layer (`PlatformClient`)
2. Maintain backward compatibility with GitHub
3. Test with both platforms
4. Document platform-specific behavior
5. Update `swebench/collect/README.md` with GitLab examples

## Code Review

All contributions require code review. Reviewers will check for:

- Code quality and style
- Test coverage
- Documentation completeness
- Backward compatibility
- Performance implications

## Getting Help

- **Questions**: Open a GitHub issue with the `question` label
- **Bugs**: Open a GitHub issue with the `bug` label
- **Feature Requests**: Open a GitHub issue with the `enhancement` label
- **Security Issues**: Email the maintainers directly

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Acknowledgments

Thank you for contributing to SWE-bench! Your efforts help make software engineering benchmarks better for everyone.
