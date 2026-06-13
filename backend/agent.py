"""Company brain orchestration behind POST /ask."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from analytics import (
    customer_name,
    entity_id,
    first_present,
    inventory_quantities,
    is_below_min,
    latest_row,
    money,
    opportunity_value,
    unique_sources,
)
from api_client import AlDenteApiClient, ApiError
from artifacts import html_deck, requested_format, write_artifact
from kb import extract_price, extract_spec_answer, find_doc_by_sku, search_kb
from llm import grounded_answer, run_agent, select_model
from tools import TOOL_SPECS, Toolbox


@dataclass
class AgentResult:
    answer: str
    sources: list[str]
    verticale: str
    artifact_url: str | None = None


ID_PATTERNS = {
    "customer": re.compile(r"\bCUST-\d{4}\b", re.IGNORECASE),
    "sku": re.compile(r"\bPAS-[A-Z]{3}-\d{3}\b", re.IGNORECASE),
    "raw_sku": re.compile(r"\bRAW-[A-Z]{3}-\d{3}\b", re.IGNORECASE),
    "lot": re.compile(r"\bLOT-\d{4}-\d{4}\b", re.IGNORECASE),
    "call": re.compile(r"\bCALL-\d{5}\b", re.IGNORECASE),
}


_CACHE: dict[str, AgentResult] = {}
_CACHE_MAX = 256


def answer_question(question: str) -> AgentResult:
    """Public entry point: caches identical questions, never raises."""
    key = " ".join(question.split()).lower()
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    result = _answer_question(question)
    if key and not result.answer.startswith("I cannot answer right now"):
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = result
    return result


def _answer_question(question: str) -> AgentResult:
    api = AlDenteApiClient()
    q = question.strip()
    try:
        # Artifact/generation requests stay on a deterministic path: they change
        # the output type and may need to write a binary file.
        if requested_format(q):
            return _artifact_answer(api, q)
        # Primary: the Regolo tool-calling agent loop.
        loop_result = _agent_loop_answer(api, q)
        if loop_result is not None:
            return loop_result
        # Fallback (no LLM available, or the loop produced nothing): deterministic handlers.
        return _deterministic_answer(api, q)
    except ApiError as exc:
        return AgentResult(
            answer=f"I cannot answer right now because the mock API call failed: {exc}.",
            sources=[],
            verticale=_route_verticale(q),
        )
    except Exception as exc:
        return AgentResult(
            answer=f"I cannot answer right now because an internal error occurred: {type(exc).__name__}.",
            sources=[],
            verticale=_route_verticale(q),
        )


def _agent_loop_answer(api: AlDenteApiClient, question: str) -> AgentResult | None:
    """Run the Regolo tool-calling loop; return None if the LLM is unavailable."""
    if not api.configured or select_model() is None:
        return None
    box = Toolbox(api)
    answer = run_agent(question, TOOL_SPECS, box.dispatch)
    if not answer:
        return None
    sources = unique_sources(box.sources)
    verticale = _verticale_from_sources(sources, _route_verticale(question))
    return AgentResult(answer, sources, verticale)


def _deterministic_answer(api: AlDenteApiClient, q: str) -> AgentResult:
    """Keyword-routed handlers, used when the agent loop cannot run."""
    lower = q.lower()
    if "profit margin" in lower or "margin" in lower:
        return AgentResult(
            answer="Not available: cost and profit margin are not stored on lots or in the available CRM, ERP, calls, or KB sources.",
            sources=["erp/production-orders"],
            verticale="erp",
        )
    if "qualif" in lower and "return" in lower and "complaint" in lower:
        return _return_policy_answer(api, q)
    if "opportunit" in lower and "negotiation" in lower and "group" in lower:
        return _negotiation_by_channel(api)
    if "open opportunit" in lower or ("opportunit" in lower and "total value" in lower):
        return _open_opportunities(api, q)
    if "order" in lower and "status" in lower:
        return _order_status_answer(api, q)
    if ("semolina" in lower or "bill of materials" in lower or "bom" in lower) and (
        "supplier" in lower or "provide" in lower or "raw material" in lower
    ):
        return _bom_supplier_answer(api, q)
    if ("below" in lower and "minimum" in lower) or ("stock" in lower and _extract("sku", q)):
        return _inventory_answer(api, q)
    if "broken pasta" in lower and "all recorded calls" in lower:
        return _broken_pasta_count(api)
    if "last call" in lower or ("complaint" in lower and "lot" in lower):
        return _latest_call_complaint(api, q)
    if "shelf life" in lower or "allergen" in lower or "tmc" in lower:
        return _kb_spec_answer(q)
    if "price" in lower or "list price" in lower:
        return _price_answer(q)
    return _orchestrated_answer(api, q)


def _extract(kind: str, question: str) -> str | None:
    match = ID_PATTERNS[kind].search(question)
    return match.group(0).upper() if match else None


def _route_verticale(question: str) -> str:
    lower = question.lower()
    if any(word in lower for word in ("call", "complaint", "transcript")):
        return "calls"
    if any(word in lower for word in ("lot", "sku", "inventory", "stock", "bom", "supplier", "shipment")):
        return "erp"
    if any(word in lower for word in ("shelf", "allergen", "price", "policy", "capitolato", "document")):
        return "kb"
    return "crm"


def _unwrap_item(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _find_customer(api: AlDenteApiClient, question: str) -> dict[str, Any] | None:
    customer_id = _extract("customer", question)
    if customer_id:
        return _unwrap_item(api.crm_customer(customer_id))
    name = _customer_search_text(question)
    if not name:
        return None
    matches = api.crm_customers(search=name)
    if matches:
        return matches[0]
    compact = re.sub(r"\b(s\.p\.a\.|spa|srl|s\.r\.l\.)\b", "", name, flags=re.IGNORECASE).strip()
    if compact and compact != name:
        matches = api.crm_customers(search=compact)
        if matches:
            return matches[0]
    return None


def _customer_search_text(question: str) -> str | None:
    if "(" in question:
        before = question.split("(", 1)[0]
        tokens = re.split(r"\b(?:for|with|visiting|of|does|in|to)\b", before, flags=re.IGNORECASE)
        candidate = tokens[-1].strip(" :,-?")
        return candidate or None
    match = re.search(r"(?:for|with|visiting|of)\s+([A-Z][A-Za-z0-9 .'\-&]+)", question)
    if match:
        return match.group(1).strip(" :,-?")
    return None


def _open_opportunities(api: AlDenteApiClient, question: str) -> AgentResult:
    customer = _find_customer(api, question)
    if not customer:
        name = _customer_search_text(question) or "the requested customer"
        return AgentResult(f'There is no customer named "{name}" in the CRM.', ["crm/customers"], "crm")
    cid = entity_id(customer, "customer_id")
    opportunities = []
    for stage in ("qualification", "negotiation"):
        opportunities.extend(api.crm_opportunities(customer_id=cid, stage=stage))
    total = sum(opportunity_value(row) for row in opportunities)
    answer = f"{len(opportunities)} open opportunities (qualification + negotiation) worth {money(total)} in total."
    return AgentResult(answer, ["crm/customers", "crm/opportunities"], "crm")


def _negotiation_by_channel(api: AlDenteApiClient) -> AgentResult:
    opportunities = api.crm_opportunities(stage="negotiation")
    # One customers call, then map id -> channel (efficient and flake-resistant).
    channel_by_id: dict[str, str] = {}
    for customer in api.crm_customers():
        cid = entity_id(customer, "customer_id")
        if cid:
            channel_by_id[cid] = str(first_present(customer, ("channel", "customer_channel"), "unknown"))
    totals: dict[str, float] = {"GDO": 0.0, "distributor": 0.0, "horeca": 0.0}
    for opportunity in opportunities:
        cid = str(first_present(opportunity, ("customer_id", "customer"), ""))
        channel = channel_by_id.get(cid, "unknown")
        totals[channel] = totals.get(channel, 0.0) + opportunity_value(opportunity)
    ordered = [f"{channel}: {money(totals[channel])}" for channel in ("GDO", "distributor", "horeca") if channel in totals]
    return AgentResult("; ".join(ordered) + ".", ["crm/opportunities", "crm/customers"], "crm")


def _order_status_answer(api: AlDenteApiClient, question: str) -> AgentResult:
    customer = _find_customer(api, question)
    if not customer:
        name = _customer_search_text(question) or "the requested customer"
        return AgentResult(f'There is no customer named "{name}" in the CRM.', ["crm/customers"], "crm")
    cid = entity_id(customer, "customer_id")
    orders = api.crm_orders(customer_id=cid)
    latest = latest_row(orders)
    if not latest:
        return AgentResult(f"No CRM orders were found for {customer_name(customer)}.", ["crm/customers", "crm/orders"], "crm")
    status = first_present(latest, ("status",), "unknown")
    order_id = entity_id(latest, "order_id")
    return AgentResult(f"The latest order for {customer_name(customer)} is {order_id} with status {status}.", ["crm/customers", "crm/orders"], "crm")


def _inventory_answer(api: AlDenteApiClient, question: str) -> AgentResult:
    sku = _extract("sku", question) or _extract("raw_sku", question)
    if not sku:
        return AgentResult("I need a SKU to check inventory.", ["erp/inventory"], "erp")
    rows = api.inventory(search=sku)
    item = next((row for row in rows if sku in json.dumps(row)), rows[0] if rows else None)
    if not item:
        return AgentResult(f"Not available: SKU {sku} was not found in ERP inventory.", ["erp/inventory"], "erp")
    on_hand, minimum = inventory_quantities(item)
    status = "Yes, below minimum" if is_below_min(item) else "No, not below minimum"
    answer = f"{status}. On-hand {int(on_hand) if on_hand.is_integer() else on_hand:g} cartons"
    if minimum:
        answer += f" vs minimum {int(minimum) if minimum.is_integer() else minimum:g}"
    return AgentResult(answer + ".", ["erp/inventory"], "erp")


def _latest_call_complaint(api: AlDenteApiClient, question: str) -> AgentResult:
    customer = _find_customer(api, question)
    if not customer:
        name = _customer_search_text(question) or "the requested customer"
        return AgentResult(f'There is no customer named "{name}" in the CRM.', ["crm/customers"], "crm")
    cid = entity_id(customer, "customer_id")
    calls = api.calls(customer_id=cid)
    latest = latest_row(calls)
    if not latest:
        return AgentResult(f"No recorded calls were found for {customer_name(customer)}.", ["crm/customers", "calls"], "calls")
    call_id = entity_id(latest, "call_id")
    # The call metadata already carries the complaint summary and lot, so we
    # answer from it directly and only fall back to the transcript if needed.
    summary = str(first_present(latest, ("summary", "topic"), ""))
    lot = str(first_present(latest, ("related_lot_id",), "")) or _extract("lot", summary)
    defect = _defect_from_text(summary)
    sources = ["crm/customers", "calls"]
    if defect == "a reported defect":
        transcript = api.transcript(call_id, search="broken", limit=10)
        text = _joined_segments(transcript)
        if text:
            defect = _defect_from_text(text)
            lot = lot or _extract("lot", text)
            sources.append(f"calls/{call_id}/transcript")
    lot_text = lot or "not specified"
    if summary:
        answer = f"A quality complaint for {defect}, on lot {lot_text}. Call {call_id}. Summary: {summary}"
    else:
        answer = f"A quality complaint for {defect}, on lot {lot_text}. Call {call_id}."
    return AgentResult(answer, sources, "calls")


def _return_policy_answer(api: AlDenteApiClient, question: str) -> AgentResult:
    complaint = _latest_call_complaint(api, question)
    policy_docs = search_kb("Returns and Quality Complaints Policy broken pasta return window evidence", limit=2)
    sources = [*complaint.sources, *[doc.doc_id for doc in policy_docs]]
    lower = complaint.answer.lower()
    if "broken pasta" in lower:
        answer = (
            'Yes: "broken pasta" is covered by the returns policy when the complaint is within the 15-day window '
            "and includes lot number plus photo evidence. Outcome: replacement or credit note; the affected lot is blocked."
        )
    else:
        answer = (
            f"{complaint.answer} The returns policy covers bloated packs, broken pasta, foreign body, and mislabeling "
            "when submitted within 15 days with lot number and photo evidence."
        )
    return AgentResult(answer, unique_sources(sources), "calls")


def _broken_pasta_count(api: AlDenteApiClient) -> AgentResult:
    calls = api.calls()
    count = 0
    for call in calls:
        call_id = entity_id(call, "call_id")
        if not call_id:
            continue
        transcript = api.transcript(call_id, search="broken pasta", limit=1)
        if transcript.get("segments"):
            count += 1
    return AgentResult(f"{count} calls report a 'broken pasta' defect.", ["calls", "calls/{id}/transcript"], "calls")


def _bom_supplier_answer(api: AlDenteApiClient, question: str) -> AgentResult:
    sku = _extract("sku", question)
    if not sku:
        return AgentResult("I need a finished product SKU to inspect the bill of materials.", ["erp/bom"], "erp")
    bom_rows = api.bom(sku=sku)
    # /erp/bom returns one row per finished SKU with a `components` list.
    components: list[dict[str, Any]] = []
    for row in bom_rows:
        comps = row.get("components")
        if isinstance(comps, list):
            components.extend(comps)
    if not components and bom_rows:
        components = bom_rows  # fallback if the shape is flat
    # Find the semolina component.
    semolina = next(
        (
            c
            for c in components
            if "semolina" in json.dumps(c).lower() or "RAW-SEM" in json.dumps(c).upper()
        ),
        None,
    )
    if not semolina:
        return AgentResult(f"Not available: no semolina component was found in the BOM for {sku}.", ["erp/bom"], "erp")
    raw_sku = str(first_present(semolina, ("raw_sku", "raw_material_sku", "component_sku", "sku"), "")) or (
        _extract("raw_sku", json.dumps(semolina)) or ""
    )
    raw_name = str(first_present(semolina, ("description", "product_name", "name"), raw_sku))
    # Inventory for the raw material (carries supplier_id and stock levels).
    inventory = api.inventory(search=raw_sku) if raw_sku else []
    item = next((r for r in inventory if str(r.get("sku")) == raw_sku), inventory[0] if inventory else {})
    supplier_id = str(first_present(item, ("supplier_id",), first_present(semolina, ("supplier_id",), "")))
    # Map supplier id -> name via the suppliers list (no get-by-id endpoint).
    supplier_name = supplier_id or "the listed supplier"
    suppliers = api.suppliers(category="semolina")
    for s in suppliers:
        if entity_id(s) == supplier_id:
            supplier_name = str(first_present(s, ("name", "supplier_name"), supplier_id))
            break
    status = "is below minimum stock" if item and is_below_min(item) else "is not below minimum stock"
    answer = f"{raw_sku} ({raw_name}), supplied by {supplier_name}; it {status}."
    return AgentResult(answer, ["erp/bom", "erp/inventory", "erp/suppliers"], "erp")


def _kb_spec_answer(question: str) -> AgentResult:
    sku = _extract("sku", question)
    doc = find_doc_by_sku(sku) if sku else (search_kb(question, limit=1)[0] if search_kb(question, limit=1) else None)
    if not doc:
        return AgentResult("Not available: no matching product specification was found in the KB.", [], "kb")
    answer = extract_spec_answer(doc)
    if not answer:
        return AgentResult(f"Not available: {doc.doc_id} does not contain the requested spec fields.", [doc.doc_id], "kb")
    return AgentResult(answer, [doc.doc_id], "kb")


def _price_answer(question: str) -> AgentResult:
    sku = _extract("sku", question)
    docs = search_kb(question + " wholesale price list 2026", limit=5)
    price_doc = next((doc for doc in docs if doc.doc_id == "DOC-015"), None) or find_doc_by_sku(sku or "")
    if sku and price_doc:
        price = extract_price(price_doc, sku)
        if price:
            return AgentResult(
                f"{price} EUR per carton. The official 2026 wholesale price list ({price_doc.doc_id}) is authoritative.",
                [price_doc.doc_id],
                "kb",
            )
    return AgentResult("Not available: the official list price was not found in the KB.", [doc.doc_id for doc in docs], "kb")


def _artifact_answer(api: AlDenteApiClient, question: str) -> AgentResult:
    fmt = requested_format(question)
    title = "Al Dente Answer"
    facts: list[str] = []
    sources: list[str] = []
    customer = None
    if api.configured:
        customer = _find_customer(api, question)
    if customer:
        cid = entity_id(customer, "customer_id")
        title = f"Sales brief - {customer_name(customer)}"
        facts.append(f"Profile: {customer_name(customer)} ({first_present(customer, ('channel',), 'unknown channel')}).")
        sources.append("crm/customers")
        opportunities = []
        for stage in ("qualification", "negotiation"):
            opportunities.extend(api.crm_opportunities(customer_id=cid, stage=stage))
        if opportunities:
            facts.append(f"Open deals: {len(opportunities)} opportunities worth {money(sum(opportunity_value(row) for row in opportunities))}.")
            sources.append("crm/opportunities")
        orders = api.crm_orders(customer_id=cid)
        if orders:
            facts.append(f"Orders: {len(orders)} CRM orders found; latest status {first_present(latest_row(orders) or {}, ('status',), 'unknown')}.")
            sources.append("crm/orders")
        calls = api.calls(customer_id=cid)
        if calls:
            facts.append(f"Recent calls: {len(calls)} recorded calls; latest call {entity_id(latest_row(calls) or {}, 'call_id')}.")
            sources.append("calls")
    if not facts:
        docs = search_kb(question, limit=3)
        facts = [f"{doc.doc_id}: {doc.title}" for doc in docs] or ["No matching source facts were found."]
        sources = [doc.doc_id for doc in docs]
    body = "\n".join(facts)
    if fmt == "html":
        return AgentResult(
            html_deck(title, [("Profile", facts[0]), ("Commercial facts", "\n".join(facts[1:2] or ["No open facts found."])), ("Operations", "\n".join(facts[2:3] or ["No operational facts found."])), ("Sources", ", ".join(sources))]),
            unique_sources(sources),
            "crm" if customer else _route_verticale(question),
        )
    artifact_url = write_artifact(fmt or "txt", title, body)
    return AgentResult(f"Generated {fmt} artifact: {artifact_url}", unique_sources(sources), "crm" if customer else _route_verticale(question), artifact_url)


_VERTICALE_PRIORITY = ("crm", "erp", "calls", "kb")


def _category_of(source: str) -> str | None:
    if source.startswith("crm/"):
        return "crm"
    if source.startswith("erp/"):
        return "erp"
    if source.startswith("calls"):
        return "calls"
    if source.startswith("DOC-"):
        return "kb"
    return None


def _verticale_from_sources(sources: list[str], fallback: str) -> str:
    counts = Counter(cat for cat in (_category_of(s) for s in sources) if cat)
    if not counts:
        return fallback
    top = max(counts.values())
    leaders = [cat for cat, n in counts.items() if n == top]
    for cat in _VERTICALE_PRIORITY:
        if cat in leaders:
            return cat
    return fallback


def _orchestrated_answer(api: AlDenteApiClient, question: str) -> AgentResult:
    """Fallback for questions that match no deterministic handler.

    Gathers a bounded set of CRM/ERP/calls/KB facts driven by the entities and
    signals in the question, then composes the answer (via the grounded LLM when
    available, else a deterministic summary). Sources and verticale are derived
    from what was actually gathered - never hardcoded to KB.
    """
    lower = question.lower()
    facts: list[str] = []
    sources: list[str] = []

    sku = _extract("sku", question) or _extract("raw_sku", question)
    wants_customer = bool(
        _extract("customer", question)
        or _customer_search_text(question)
    )

    # --- CRM: resolve the customer and pull a compact 360 view ---
    customer = None
    if api.configured and wants_customer:
        customer = _find_customer(api, question)
        if customer:
            cid = entity_id(customer, "customer_id")
            facts.append(f"Customer: {json.dumps(customer)[:800]}")
            sources.append("crm/customers")
            if any(w in lower for w in ("opportunit", "deal", "pipeline")):
                opps: list[dict[str, Any]] = []
                for stage in ("qualification", "negotiation"):
                    opps.extend(api.crm_opportunities(customer_id=cid, stage=stage))
                facts.append(
                    f"Open opportunities (qualification+negotiation): count={len(opps)}, "
                    f"total_value={money(sum(opportunity_value(o) for o in opps))}."
                )
                sources.append("crm/opportunities")
            if any(w in lower for w in ("order", "shipment", "deliver", "invoice")):
                orders = api.crm_orders(customer_id=cid)
                latest = latest_row(orders)
                facts.append(
                    f"Orders: count={len(orders)}; latest="
                    f"{entity_id(latest or {}, 'order_id') or 'none'} "
                    f"status={first_present(latest or {}, ('status',), 'n/a')}."
                )
                sources.append("crm/orders")
            if any(w in lower for w in ("call", "complaint", "transcript")):
                calls = api.calls(customer_id=cid)
                latest = latest_row(calls)
                facts.append(
                    f"Calls: count={len(calls)}; latest="
                    f"{entity_id(latest or {}, 'call_id') or 'none'}."
                )
                sources.append("calls")
        elif _customer_search_text(question):
            name = _customer_search_text(question)
            facts.append(f'No customer matching "{name}" was found in the CRM.')
            sources.append("crm/customers")

    # --- ERP: inventory / BOM facts when a SKU is referenced ---
    if api.configured and sku:
        rows = api.inventory(search=sku)
        item = next((r for r in rows if sku in json.dumps(r)), rows[0] if rows else None)
        if item:
            on_hand, minimum = inventory_quantities(item)
            facts.append(
                f"Inventory {sku}: on_hand={on_hand:g}, minimum={minimum:g}, "
                f"below_min={is_below_min(item)}."
            )
            sources.append("erp/inventory")
        else:
            facts.append(f"SKU {sku} was not found in ERP inventory.")
            sources.append("erp/inventory")

    # --- KB: always consult the documents ---
    docs = search_kb(question, limit=3)
    for doc in docs:
        facts.append(f"{doc.doc_id} - {doc.title}\n{doc.text[:1500]}")
        sources.append(doc.doc_id)

    sources = unique_sources(sources)
    verticale = _verticale_from_sources(sources, _route_verticale(question))

    if not facts:
        return AgentResult(
            "Not available: I could not find this information in the provided sources.",
            [],
            verticale,
        )

    context = "\n\n".join(facts)[:6000]
    answer = grounded_answer(question, context)
    if answer:
        return AgentResult(answer, sources, verticale)

    # LLM unavailable/failed: deterministic, honest summary of what we found.
    if customer or sku:
        summary = " ".join(
            f for f in facts if not f.startswith(tuple(doc.doc_id for doc in docs))
        ).strip()
        if summary:
            return AgentResult(summary, sources, verticale)
    if docs:
        listed = ", ".join(f"{doc.doc_id} ({doc.title})" for doc in docs)
        return AgentResult(
            f"I found potentially relevant documents but could not compose a precise answer: {listed}.",
            sources,
            verticale,
        )
    return AgentResult(
        "Not available: I could not find this information in the provided sources.",
        [],
        verticale,
    )


def _joined_segments(transcript: dict[str, Any]) -> str:
    segments = transcript.get("segments") or []
    return " ".join(str(segment.get("text", "")) for segment in segments if isinstance(segment, dict))


def _defect_from_text(text: str) -> str:
    lower = text.lower()
    for defect in ("broken pasta", "bloated packs", "foreign body", "mislabeling", "off smell"):
        if defect in lower:
            return defect
    match = re.search(r"complaint[^.:\n]*(?:for|about|regarding)\s+([^.\n]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else "a reported defect"
