"""Whole-document lexical retrieval over backend/data/kb."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.IGNORECASE)


@dataclass(frozen=True)
class KbDocument:
    doc_id: str
    title: str
    path: Path
    text: str
    tokens: frozenset[str]


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def _doc_id(path: Path, text: str) -> str:
    match = re.search(r"Document ID:\*\*\s*(DOC-\d{3})", text)
    if match:
        return match.group(1)
    return path.stem


@lru_cache(maxsize=1)
def load_documents() -> tuple[KbDocument, ...]:
    kb_dir = Path(__file__).resolve().parent / "data" / "kb"
    docs: list[KbDocument] = []
    for path in sorted(kb_dir.glob("DOC-*.md")):
        text = path.read_text(encoding="utf-8")
        first_line = next((line for line in text.splitlines() if line.startswith("#")), path.stem)
        docs.append(
            KbDocument(
                doc_id=_doc_id(path, text),
                title=first_line.lstrip("# ").strip(),
                path=path,
                text=text,
                tokens=frozenset(tokenize(text)),
            )
        )
    return tuple(docs)


def search_kb(question: str, *, limit: int = 4) -> list[KbDocument]:
    query_tokens = tokenize(question)
    if not query_tokens:
        return []
    query_set = set(query_tokens)
    scored: list[tuple[float, KbDocument]] = []
    for doc in load_documents():
        score = 0.0
        for token in query_tokens:
            if token in doc.tokens:
                score += 3.0 if "-" in token or token.startswith(("pas", "doc")) else 1.0
        if query_set and doc.title:
            title_tokens = set(tokenize(doc.title))
            score += len(query_set & title_tokens) * 2.0
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [doc for _, doc in scored[:limit]]


def find_doc_by_sku(sku: str) -> KbDocument | None:
    sku_lower = sku.lower()
    for doc in load_documents():
        if sku_lower in doc.text.lower():
            return doc
    return None


def extract_spec_answer(doc: KbDocument) -> str | None:
    shelf = re.search(r"Shelf life[^\n|]*\|\s*([^|\n]+)\|", doc.text, re.IGNORECASE)
    contains = re.search(r"\*\*Contains:\*\*\s*([^\n]+)", doc.text, re.IGNORECASE)
    may_contain = re.search(r"\*\*May contain \(traces\):\*\*\s*([^\n]+)", doc.text, re.IGNORECASE)
    parts: list[str] = []
    if shelf:
        parts.append(f"Shelf life {shelf.group(1).strip()}.")
    if contains:
        parts.append(f"Allergens: {contains.group(1).strip()}.")
    if may_contain:
        parts.append(f"May contain: {may_contain.group(1).strip()}.")
    return " ".join(parts) if parts else None


def extract_price(doc: KbDocument, sku: str) -> str | None:
    row = re.search(rf"\|\s*{re.escape(sku)}\s*\|[^|]*\|[^|]*\|\s*([0-9]+(?:\.[0-9]+)?)\s*\|", doc.text)
    if row:
        return row.group(1)
    detail = re.search(rf"###\s*{re.escape(sku)}[^\n]*\n-\s*\*\*List price:\*\*\s*EUR\s*([0-9.]+)", doc.text)
    if detail:
        return detail.group(1)
    return None


def excerpt(doc: KbDocument, terms: list[str], *, radius: int = 2) -> str:
    lines = doc.text.splitlines()
    lowered = [term.lower() for term in terms if term]
    for index, line in enumerate(lines):
        if any(term in line.lower() for term in lowered):
            start = max(index - radius, 0)
            end = min(index + radius + 1, len(lines))
            return "\n".join(lines[start:end])
    return "\n".join(lines[: min(12, len(lines))])
