# Copilot instructions for Laborster

## Project summary

- `app/main.py` hosts the FastAPI API, ORM models, and static frontend
- `frontend/` is a static Vue 3 UI served directly by FastAPI
- `worker/main.py` is a separate Python worker that talks to `/api`
- Runtime data is stored under `storage/`
- Deployment uses `docker compose`

## UI change rules

- For branding or icon requests, keep the existing page layout and interaction structure unless the user explicitly asks for a redesign
- Prefer the smallest visual change that satisfies the request
- Keep UI text in Chinese unless the existing screen already uses English labels

## Delivery workflow

After completing code changes, unless the user explicitly says not to:

1. Commit the changes
2. Push the current branch to origin
3. Run `docker compose down`
4. Run `docker compose up --build -d`

## Useful commands

```bash
docker compose down
docker compose up --build -d
python -m compileall app worker
```
