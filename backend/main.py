"""Al Dente Company Brain - backend entry point.

Your job: implement the agent behind POST /ask. It orchestrates the Al Dente
mock APIs (CRM / ERP / call logs) and a knowledge base you build over data/kb/,
then answers with text or an artifact. Full spec and rules in AGENTS.md.

The /ask contract below is FROZEN - the automated evaluator depends on it.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import answer_question

load_dotenv()

app = FastAPI(title="Al Dente Company Brain")

_STATIC = Path(__file__).resolve().parent / "static"
_FILES = _STATIC / "files"
_FILES.mkdir(parents=True, exist_ok=True)

# Binary artifacts (docx / pptx / pdf / xlsx) you generate at request time go in
# static/files/ and are served from /files/<name> by this same backend.
# artifact_url must be ABSOLUTE: f"{os.environ['PUBLIC_BASE_URL']}/files/<name>"
app.mount("/files", StaticFiles(directory=_FILES), name="files")


@app.get("/", include_in_schema=False)
def ui() -> FileResponse:
    """Placeholder page. Building a minimal UI is part of the challenge:
    it must exist and work, but it is not graded - replace static/index.html
    (or serve your own frontend)."""
    return FileResponse(_STATIC / "index.html")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)


class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    verticale: str  # one of: "crm", "erp", "calls", "kb"
    artifact_url: str | None = None  # only for docx/pptx/pdf/xlsx questions


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    result = answer_question(request.question)
    return AskResponse(
        answer=result.answer,
        sources=result.sources,
        verticale=result.verticale,
        artifact_url=result.artifact_url,
    )


@app.get("/graph")
def graph() -> dict[str, list[dict[str, str]]]:
    """Seed graph for the required UI visualization."""
    return {
        "nodes": [
            {"id": "customers", "label": "Customers", "type": "group"},
            {"id": "crm", "label": "CRM", "type": "source"},
            {"id": "erp", "label": "ERP", "type": "source"},
            {"id": "calls", "label": "Call logs", "type": "source"},
            {"id": "kb", "label": "Knowledge base", "type": "source"},
            {"id": "products", "label": "Finished pasta SKUs", "type": "group"},
            {"id": "lots", "label": "Production lots", "type": "group"},
            {"id": "raw", "label": "Raw materials", "type": "group"},
            {"id": "suppliers", "label": "Suppliers", "type": "group"},
            {"id": "policies", "label": "Policies and price list", "type": "group"},
        ],
        "links": [
            {"source": "customers", "target": "crm", "label": "profiles, deals, orders"},
            {"source": "customers", "target": "calls", "label": "complaints, negotiations"},
            {"source": "customers", "target": "lots", "label": "orders drive production"},
            {"source": "products", "target": "kb", "label": "spec sheets"},
            {"source": "products", "target": "lots", "label": "manufactured as"},
            {"source": "products", "target": "raw", "label": "BOM uses"},
            {"source": "raw", "target": "suppliers", "label": "provided by"},
            {"source": "lots", "target": "erp", "label": "production, inventory, shipments"},
            {"source": "policies", "target": "kb", "label": "returns, quality, prices"},
            {"source": "calls", "target": "policies", "label": "complaints checked against"},
        ],
    }
