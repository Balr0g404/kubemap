# Contributing

Bug reports and focused pull requests are welcome. For vulnerabilities, follow [SECURITY.md](SECURITY.md).

## Development

Use Python 3.11 or newer, uv, Node.js 22 or newer and npm. No cluster is needed for tests.

```bash
uv sync --locked --group dev
npm ci --prefix web
npm test --prefix web
npm run build --prefix web
uv run --frozen pytest -q
```

For the desktop and its graphical smoke test, install the `desktop` group as described in the README. The application uses PySide6; do not install PyQt alongside it in the development environment.

The GitHub Actions workflow runs the existing Python tests on Python 3.11 and 3.13, and runs the frontend tests, dependency audit and production build with Node.js 24. A separate Ubuntu job builds the PySide6 desktop Debian package and verifies its startup and notices.

## Changes

Open an issue before a large feature or dependency change. Keep pull requests focused and describe the problem, resulting behavior and checks performed. Add a regression test for changed logic using the existing pytest and Node test suites.

Use fictional resource names and reserved example domains/IP addresses. Never include real kubeconfigs, credentials, customer data or infrastructure exports. Screenshots in this repository come from the simulated cluster in `tests/desktop_smoke.py`.

Preserve the read-only collection transport. New operational capabilities must be explicit, scoped to the selected connection, validated on the server and tested without a real cluster. Do not add automatic Kubernetes changes or telemetry.

Contributions are distributed under the project's MIT license. Keep the notices of third-party components and update the lockfiles when changing dependencies.
