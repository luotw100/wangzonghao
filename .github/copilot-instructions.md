# Copilot instructions for Laborster

## What this project is

Laborster is an AI role-debugging workbench for private chat scenarios.

- A **Robot** stores persona configuration, mainly `name` and `system_prompt`
- A **Conversation** stores per-user context, mainly `title` and `user_profile`
- User messages create **Task** records
- The **worker** polls tasks, calls an OpenAI-compatible LLM, and creates **PlannedReply** records
- Planned replies are sent later as real robot messages

This project exists to test persona prompts, user profiles, delayed replies, and async orchestration together.

## Architecture

- `app/main.py` contains the FastAPI app, SQLAlchemy models, API routes, and static frontend hosting
- `frontend/` is a static UI served by FastAPI
- `worker/main.py` is a separate Python process that talks to the web API under `/api`
- Runtime data lives in `storage/`, especially `storage/chat.db` and `storage/attachments/`
- Docker Compose runs two services: `web` and `worker`

## Frontend conventions

- The frontend is **not** a bundled Node app
- It uses:
  - Vue 3 global build from CDN
  - Tailwind CDN utilities
  - plain JavaScript files under `frontend/js/`
  - plain CSS under `frontend/css/style.css`
- Keep UI text in Chinese unless there is a strong reason not to
- For branding or icon requests, prefer the smallest visual change that satisfies the request
- Do not redesign the whole page unless the user explicitly asks for a layout redesign
- Prefer extending existing modal-based editing flows over introducing a new frontend structure

## Backend conventions

- Keep API, ORM models, and schema updates aligned in `app/main.py`
- Reuse existing endpoints before adding new ones
- Preserve current behavior where:
  - user messages cancel pending planned replies for the same conversation
  - worker retries tasks up to `MAX_RETRIES`
  - planned reply timestamps are stored as UTC naive datetimes for SQLite compatibility

## Worker conventions

- `worker/config.py` should remain environment-driven for Docker Compose compatibility
- The worker communicates with the web service through `API_BASE_URL`
- LLM responses are expected to be JSON-compatible, but worker logic already includes a fallback to raw text

## When making changes

- If you add or rename a persisted field, update all relevant layers together:
  1. SQLAlchemy model
  2. Pydantic schema
  3. API handlers
  4. frontend read/write flow
  5. worker context assembly if the field affects prompting
- Do not split the frontend into a separate service unless explicitly requested
- Do not replace SQLite casually; persistence through `storage/` is part of the current deployment shape
- Prefer surgical edits over broad rewrites unless the requested change clearly requires it

## Useful commands

```bash
docker compose up --build
docker compose down
docker compose config
uv run uvicorn app.main:app --host 0.0.0.0 --port 23456
uv run python worker/main.py
python -m compileall app worker
```
