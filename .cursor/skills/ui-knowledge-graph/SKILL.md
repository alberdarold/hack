---
name: ui-knowledge-graph
description: Guides implementation of the required Al Dente UI and knowledge graph. Use when editing backend/static/index.html, graph endpoints, or frontend code that asks /ask and visualizes customers, suppliers, products, materials, and documents.
---

# UI Knowledge Graph

## Required Outcome

Build an end-to-end UI at `GET /` that lets a user:

- Type a question.
- Submit it to `POST /ask`.
- See the answer, sources, verticale, and artifact link.
- Explore a graph of company knowledge.

## Graph Content

Represent the network of:

- Customers.
- Products and finished SKUs.
- Production lots.
- Raw materials.
- Suppliers.
- KB documents and policies.

## Implementation Guidance

- Keep the UI static if possible: `backend/static/index.html`.
- Avoid separate frontend services and CORS.
- Use lightweight vanilla JavaScript/SVG/canvas unless a dependency already exists.
- The graph may use curated seed nodes initially, then improve with API-backed data.

## Guardrails

- Do not break `/ask` or `/files` routes.
- UI polish matters for Level 2, but answers and source correctness still come first.
