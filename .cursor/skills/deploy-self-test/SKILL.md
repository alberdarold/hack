---
name: deploy-self-test
description: Guides Railway deployment and challenge self-test iteration for the Al Dente backend. Use when deploying, setting env vars, checking /health or /ask, reviewing logs, or improving endpoint-check and self-test scores.
---

# Deploy Self-Test

## Railway Shape

- Deploy one service from `backend/`.
- Railway uses `backend/railway.json`, `pyproject.toml`, and `uv.lock`.
- The backend serves `/ask`, `/`, `/health`, and `/files`.

## Environment Variables

Set these locally and on Railway:

- `LLM_BASE_URL`
- `LLM_API_KEY`
- `MODEL`
- `MOCK_API_BASE_URL`
- `MOCK_API_TOKEN`
- `PUBLIC_BASE_URL`

## Checks

1. `GET /health` returns `{"status":"ok"}`.
2. `POST /ask` accepts `{"question":"..."}` with no auth.
3. `/ask` always returns HTTP 200 and the frozen JSON schema.
4. Binary artifact URLs are absolute and reachable.
5. Platform endpoint check passes before final submission.

## Iteration

- Run sample questions before hidden self-test.
- Use self-test feedback to target specific evaluator shapes.
- Redeploy after focused improvements.
- Never commit `.env` or hardcode keys.
