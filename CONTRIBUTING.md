# Contributing

Issues and focused pull requests are welcome.

1. Create a branch from `main`.
2. Install the development dependencies with `pip install -e '.[dev]'`.
3. Add tests for behavior changes.
4. Run `pytest`, `ruff check .`, `ruff format --check .`, and the Rego tests.
5. Open a pull request that explains the security impact and compatibility considerations.

Never commit secrets or production payloads. Security-sensitive changes should include an
update to the threat model when they alter a trust boundary.

