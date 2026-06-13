---
name: company-brain-orchestrator
description: Guides implementation of the Al Dente /ask agent loop, source routing, dominant verticale selection, honest abstention, and final answer composition. Use when working on backend/main.py, backend/agent.py, or any company brain orchestration logic.
---

# Company Brain Orchestrator

## Objective

Implement the brain behind `POST /ask` while preserving the frozen contract:

- Request: `{"question": str}`
- Response: `{"answer": str, "sources": list[str], "verticale": "crm" | "erp" | "calls" | "kb", "artifact_url": str | None}`
- Always return HTTP 200 with one JSON body. No auth, streaming, or job pattern.

## Workflow

1. Read `AGENTS.md`, `API.md`, and `SAMPLE_QUESTIONS.md` before major changes.
2. Route the question to the dominant source: `crm`, `erp`, `calls`, or `kb`.
3. Use deterministic handlers for known evaluator shapes before invoking the LLM.
4. Fetch facts only from Al Dente APIs and `backend/data/kb/`.
5. Compose the answer from fetched facts. If a fact is missing, say specifically what is unavailable.
6. Keep total `/ask` runtime under 30 seconds.

## Guardrails

- Never invent customers, lots, margins, prices, policies, or statuses.
- Do arithmetic in Python, not in the model prompt.
- Return source IDs and endpoint names that were actually used.
- For multi-source questions, set `verticale` to the dominant source of the answer.
