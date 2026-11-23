# Cabmora API

FastAPI backend for the Cabmora photography & videography platform.
Clean architecture — see `docs/ARCHITECTURE.md` in the `cabmora-web` repo for
the shared conventions, and `BACKEND_PLAN.md` here for the layer rules.

**Frontends live in a separate repo** (`cabmora-web`: public site + admin
console). The only thing shared between the two repos is the HTTP contract,
published at `/openapi.json`.

## Structure

```
app/
├── domain/          entities + repository interfaces   (no framework imports)
├── application/     use cases                          (depends on domain)
├── infrastructure/  SQLAlchemy models, repo impls, db  (implements domain)
└── api/             routers, schemas, DI wiring        (depends on application)
tests/
```

Dependency rule: `api → application → domain ← infrastructure`.
Nothing in `domain/` may import from any other layer.

## Run with Docker

```bash
docker compose up --build
```

- API: http://localhost:8000 · docs at `/docs`
- Postgres: `localhost:5432` — `cabmora` / `cabmora`

This publishes port 8000 on the host, which is what the `cabmora-web` dev stack
proxies to by default.

## Run locally (Python 3.12)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Tests: `pytest`

## Publishing an image for the frontends

The `cabmora-web` production stack does not build this repo — it proxies to a
deployed API. Build and push:

```bash
docker compose build api
docker tag cabmora/api:latest <registry>/cabmora/api:<tag>
docker push <registry>/cabmora/api:<tag>
```

## Configuration

Settings are read from the environment (or `.env`) by `app/core/config.py`.

| Variable | Notes |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` in deployment; SQLite default is for tests |
| `JWT_SECRET_KEY` | **rotate off the placeholder** — `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | defaults to 60 |
| `CORS_ORIGINS` | **JSON array** — pydantic-settings parses `list[str]` as JSON. `CORS_ORIGINS=["https://cabmora.com"]`, not a bare string |
| `ENVIRONMENT` | `local` / `production` |

### CORS and the frontends

In production the frontends' nginx proxies `/api` to this service, so browser
requests are **same-origin** and CORS never engages — `CORS_ORIGINS` can stay
empty. It only matters if a client is served from an origin that calls this API
directly rather than through its own proxy.

## Known gaps

1. **No migrations.** `app.main:lifespan` calls `create_tables()`, flagged in
   code as dev convenience. It cannot alter existing tables, so the first schema
   change against real data has no safe path. Alembic is the fix, and it also
   unblocks running more than one uvicorn worker (concurrent workers currently
   race on `CREATE TABLE`, which is why the Dockerfile runs a single one).
2. **No role-based authorisation.** The admin console's endpoints
   (`/api/v1/admin/*`) and a `require_role(Role.ADMIN)` dependency do not exist
   yet. Until they do, the admin UI is unprotected regardless of where it is
   hosted.
