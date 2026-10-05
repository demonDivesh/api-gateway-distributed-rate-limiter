# Contributing

1. `make install` (Python 3.14 + Node 22 required), then `make test` – everything must pass before and after your change.
2. Follow the layering in `ARCHITECTURE.md`: routes → services → infrastructure. Routes never talk to Redis/DB directly for business logic; middleware never contains business rules beyond its concern.
3. Every behaviour change needs a test. Bug fixes start with a failing test. Rate limiter changes must keep the concurrency tests green (they guard atomicity).
4. `make lint typecheck` must be clean (Ruff, mypy). Formatting: `make format`.
5. Never commit secrets; `.env` is git-ignored. Add new settings to `Settings`, `.env.example`, `docker-compose.yml` and the README table together.
6. Update `CHANGELOG.md` and, for API changes, `API.md`.
7. Commit messages: imperative mood, explain *why*. One logical change per pull request.

Security issues: see `SECURITY.md` – do not open public issues for vulnerabilities.
