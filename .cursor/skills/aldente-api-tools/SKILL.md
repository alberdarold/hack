---
name: aldente-api-tools
description: Guides efficient use of the Al Dente mock CRM, ERP, and calls APIs. Use when building API clients, query helpers, pagination, transcript search, or source-efficient data access for the challenge.
---

# Al Dente API Tools

## API Rules

- Base URL comes from `MOCK_API_BASE_URL`.
- Token comes from `MOCK_API_TOKEN`.
- Send `Authorization: Bearer $MOCK_API_TOKEN` on every mock API request.
- Never hardcode tokens or commit `.env`.

## Efficiency

- Prefer exact filters: `customer_id`, `sku`, `status`, `stage`, `search`, dates.
- Always check `pagination.total` before aggregating.
- Page list endpoints with `limit=200` only when a full aggregate is required.
- Use `/calls/{id}/transcript?search=...` instead of downloading full transcripts.

## Endpoint Families

- CRM: customers, opportunities, orders, invoices.
- ERP: production orders, inventory, suppliers, BOM, shipments.
- Calls: call metadata and transcript segments.

## Implementation Expectations

- Keep the API client thin and typed enough to avoid endpoint mistakes.
- Surface API failures as honest unavailable answers through `/ask`, not as uncaught 5xx errors.
- Include endpoint source names such as `crm/customers`, `erp/inventory`, or `calls/{id}/transcript`.
