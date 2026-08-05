# openIndu Backend

> FastAPI Web API (8004) + MCP Server (8005). Depends on PostgreSQL + Milvus + Aliyun OSS.

## Rule #1 — Agent behavior principles

This repo follows openIndu's unified principles (11 RULEs), provided by the public plugin `openindu-control-tower@openindu`.

**First step of any task: call `/principle` to load the principles.**

This repo **must not** self-host a principle copy. Principle changes go through `openIndu/control-tower`'s spec + arbiter review.

## Repo context (for agents)

| Field | Value |
| --- | --- |
| Type | `backend` (per `/route`) |
| Primary language | Python 3.11+ |
| Framework | FastAPI + SQLAlchemy + Alembic |
| Dependency mgmt | `requirements.txt` / `requirements-app.txt` / `requirements-heavy.txt` (not pyproject) |
| Lint | `ruff` (`ruff.toml`) |
| Test | `pytest` (`pytest.ini`, `tests/`) |
| Services | Web API on `:8004` (`app/web_app.py`), MCP Server on `:8005` (`app/mcp_app.py`) |
| App structure | `app/{api,core,mcp,middleware,models,services,tasks}` |
| Migrations | `alembic/` (`alembic.ini`) |
| Dependencies | PostgreSQL, Milvus (vector DB), Aliyun OSS |
| Aggregate | `openIndu-website` (submodule aggregate repo) |
| Image | `crpi-f7ll8pm177asmofl.cn-chengdu.personal.cr.aliyuncs.com/openindu/openindu-backend` |
| Production DB | see `/route` (`production_db` field) — RULE 10 applies |
| Local stack | `docker-compose.yml` |

## Design-doc workspace

Agents write SDLC artifacts to `design/<domain>/`:

| Domain | Owner agent | Path |
| --- | --- | --- |
| Business analysis | business-analyst | `design/business/` |
| Product (PRD) | product-manager | `design/product/` |
| Architecture | architect | `design/architecture/` |
| UI/UX | ui-ux-designer | `design/uiux/` |
| Database | backend | `design/database/` |
| BI / metrics | bi-analyst | `design/bi/` |
| Ops / runbooks | ops | `design/ops/` |

## Quick commands

```bash
# lint
ruff check .

# test
pytest

# local stack
docker-compose up -d

# migration
alembic upgrade head
```
