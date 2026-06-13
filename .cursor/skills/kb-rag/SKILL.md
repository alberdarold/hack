---
name: kb-rag
description: Guides retrieval over backend/data/kb markdown documents for the Al Dente challenge. Use when building KB search, document indexing, DOC source reporting, product specs, policies, price list, or customer requirement lookups.
---

# KB RAG

## Retrieval Strategy

- Load documents from `backend/data/kb/`.
- Preserve each file's `DOC-###` identifier.
- Start with whole-document lexical retrieval; these documents are short and product specs should keep shelf life and allergens together.
- Return document IDs in `sources`.

## Answering Rules

- Use KB facts for product specs, allergens, shelf life, price list, quality policy, returns policy, capitolati, and labeling requirements.
- If a phone call and an official KB document disagree, treat the official document as authoritative.
- If retrieval does not support the requested fact, answer that the information is not available in the KB.

## Implementation Expectations

- Normalize text for matching, but do not alter source IDs or quoted facts.
- Prefer precise matches on SKU, product name, document title, policy keywords, and price-list rows.
- Avoid over-chunking. Only add chunking if whole-document retrieval fails in self-tests.
