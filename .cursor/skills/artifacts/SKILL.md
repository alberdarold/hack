---
name: artifacts
description: Guides artifact generation for Al Dente answers, including inline HTML/markdown and downloadable docx, pptx, pdf, or xlsx files served from backend/static/files with artifact_url.
---

# Artifacts

## Contract

- Inline HTML or markdown artifacts go in `answer`; `artifact_url` stays `None`.
- Binary artifacts go under `backend/static/files/`.
- Binary responses must include an absolute URL: `${PUBLIC_BASE_URL}/files/<filename>`.

## Priorities

1. Facts are more important than visual style.
2. Use only facts fetched from the APIs and KB.
3. Keep artifacts deterministic where possible.
4. Use clear titles, source notes, and concise sections.

## Supported Formats

- HTML decks: return complete inline HTML in `answer`.
- `.docx`, `.pptx`, `.pdf`, `.xlsx`: create a file and return `artifact_url`.

## Guardrails

- Do not write files outside `backend/static/files/`.
- Do not include secrets or environment values in artifacts.
- If a requested binary library is unavailable, return a valid honest answer explaining artifact generation is unavailable rather than raising a 5xx.
