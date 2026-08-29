# Contributing to openIndu Backend

Thank you for contributing. Create a focused branch, keep secrets and local
`.env` files out of Git, and open a pull request against `main`.

Before submitting a pull request, run:

```bash
pip install -r requirements.txt          # or requirements-app.txt for API-only
ruff check app/
pytest -q
```

Database changes go through Alembic migrations (`alembic revision --autogenerate`).
Never point local development at a production database.

Describe the intent, blast radius, test results, and rollback approach in the
pull request. All changes require human review before merge.

## Reporting security issues

Do not open a public issue for a suspected vulnerability. See [SECURITY.md](SECURITY.md).
