"""Artifact generation helpers."""

from __future__ import annotations

import html
import os
import re
import time
import zipfile
from pathlib import Path


FILES_DIR = Path(__file__).resolve().parent / "static" / "files"


def requested_format(question: str) -> str | None:
    lower = question.lower()
    for ext in ("docx", "pptx", "pdf", "xlsx"):
        if re.search(rf"\b{ext}\b", lower):
            return ext
    if "html" in lower or "deck" in lower or "slides" in lower:
        return "html"
    return None


def html_deck(title: str, slides: list[tuple[str, str]]) -> str:
    cards = []
    for index, (heading, body) in enumerate(slides, start=1):
        cards.append(
            f"<section class=\"slide\"><span>Slide {index}</span><h2>{html.escape(heading)}</h2>"
            f"<p>{html.escape(body).replace(chr(10), '<br>')}</p></section>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><style>"
        "body{font-family:Inter,Arial,sans-serif;background:#14120b;color:#ece8dd;margin:0;padding:24px}"
        ".deck{display:grid;gap:16px}.slide{border:1px solid #3a3324;background:#1c1a12;border-radius:16px;padding:24px}"
        "span{color:#f54e00;text-transform:uppercase;letter-spacing:.12em;font-size:12px}h1,h2{margin:.2rem 0}.sources{color:#9b9684}"
        "</style></head><body><main class=\"deck\">"
        f"<h1>{html.escape(title)}</h1>{''.join(cards)}</main></body></html>"
    )


def write_artifact(fmt: str, title: str, body: str) -> str:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "artifact"
    filename = f"{safe}-{int(time.time())}.{fmt}"
    path = FILES_DIR / filename
    if fmt == "pdf":
        _write_pdf(path, title, body)
    elif fmt == "docx":
        _write_docx(path, title, body)
    elif fmt == "xlsx":
        _write_xlsx(path, title, body)
    elif fmt == "pptx":
        _write_pptx(path, title, body)
    else:
        path.write_text(body, encoding="utf-8")
    base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{base_url}/files/{filename}"


def _write_pdf(path: Path, title: str, body: str) -> None:
    text = f"{title}\n\n{body}".replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lines = text.splitlines()[:45]
    stream_lines = ["BT", "/F1 12 Tf", "50 780 Td"]
    for line in lines:
        stream_lines.append(f"({line[:95]}) Tj")
        stream_lines.append("0 -16 Td")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1", "replace")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        f"5 0 obj << /Length {len(stream)} >> stream\n".encode() + stream + b"\nendstream endobj\n",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(content))
        content.extend(obj)
    xref = len(content)
    content.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(f"trailer << /Root 1 0 R /Size {len(offsets)} >>\nstartxref\n{xref}\n%%EOF".encode())
    path.write_bytes(bytes(content))


def _write_docx(path: Path, title: str, body: str) -> None:
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{html.escape(line) or ' '}</w:t></w:r></w:p>" for line in f"{title}\n\n{body}".splitlines()
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        zf.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        zf.writestr("word/document.xml", document)


def _write_xlsx(path: Path, title: str, body: str) -> None:
    rows = [title, *body.splitlines()]
    sheet_rows = "".join(
        f'<row r="{idx}"><c r="A{idx}" t="inlineStr"><is><t>{html.escape(row)}</t></is></c></row>'
        for idx, row in enumerate(rows, start=1)
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        zf.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        zf.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Answer" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        zf.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{sheet_rows}</sheetData></worksheet>')


def _write_pptx(path: Path, title: str, body: str) -> None:
    slide_text = html.escape(f"{title}\n\n{body}")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/><Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/></Types>')
        zf.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>')
        zf.writestr("ppt/presentation.xml", '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldIdLst><p:sldId id="256" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></p:sldIdLst></p:presentation>')
        zf.writestr("ppt/_rels/presentation.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>')
        zf.writestr("ppt/slides/slide1.xml", f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/><a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:r><a:t>{slide_text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
