# DocPipeAI (portfolio snapshot)

Sanitized, **non-production** snapshot of a real engineering document pipeline:

PDF / Excel / Word import → structured pipeline data → Word passport generation.

This public tree is intentionally reduced under a strict NDA.

## What this shows

- Layered backend: `api` → `application` → `domain` → `infrastructure` (FastAPI, async SQLAlchemy, Alembic)
- Background jobs with REST + WebSocket progress
- Domain parsers for specification / Excel / supports / armature
- Passport `.docx` export builders
- Vanilla JS frontend served by the same FastAPI app
- Docker Compose + optional Nginx TLS sample (`example.com` placeholders only)
- Unit tests with **synthetic** line codes and fixtures

## What was removed or replaced (NDA)

- All secrets (`.env` never shipped; use `.env.example`)
- Client drawings, OCR crops, parsed OCR dumps
- Production Word passport template
- Production hostnames, IPs, certificates, org branding
- Client project / line identifiers in configs and tests (replaced with `ПСИ00000`, `XX01-…`, etc.)
- Full operational playbooks and proprietary catalog dumps (minimal demo JSON only)

This is **not** a deployable copy of a customer system and must not be treated as one.

## Stack

Python 3.13 · `uv` · FastAPI · MySQL 8 · SQLAlchemy async · Alembic · vanilla JS UI

## Local run (demo skeleton)

```bash
cp .env.example .env
# fill placeholders; never commit .env
uv sync
uv run uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

- UI: `http://localhost:8000/`
- OpenAPI: `http://localhost:8000/docs`
- Tests: `uv run pytest -q`

Passport generation needs your own Word template at `WORD_TEMPLATE_PATH` (see `data/raw/docx/README.md`).

## Architecture (short)

```
backend/app/api/            HTTP, cookies, WebSocket
backend/app/application/    jobs, import orchestration, passports
backend/app/domain/         parsers & pipeline models (no FastAPI)
backend/app/infrastructure/ DB, file I/O, docx export
frontend/                   pages + messages.js i18n strings
data/config/                minimal demo JSON catalogs
```

## License / confidentiality

Private customer work remains under NDA. This repository is a scrubbed portfolio excerpt for demonstrating architecture and engineering practice only. Do not reverse-engineer customer projects from it; identifiers here are synthetic.
