"""Deterministic tools for the Regolo agent loop.

Each tool reads only the Al Dente APIs or the bundled KB, does its own
pagination and arithmetic in Python, and returns a compact string the model can
quote verbatim. Every tool records the canonical source ids it touched so the
orchestrator can build `sources` and the dominant `verticale`.
"""

from __future__ import annotations

import json
import re
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
)
from api_client import AlDenteApiClient
from kb import extract_price, extract_spec_answer, find_doc_by_sku, search_kb

_DEFECTS = ("broken pasta", "bloated packs", "foreign body", "mislabeling", "off smell")


def _defect_from_text(text: str) -> str:
    lower = text.lower()
    for defect in _DEFECTS:
        if defect in lower:
            return defect
    match = re.search(r"complaint[^.:\n]*(?:for|about|regarding)\s+([^.\n]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else "a reported defect"


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


class Toolbox:
    """Holds the API client and accumulates the sources used across tool calls."""

    def __init__(self, api: AlDenteApiClient) -> None:
        self.api = api
        self.sources: list[str] = []

    def _add(self, *sources: str) -> None:
        self.sources.extend(sources)

    # --- CRM -------------------------------------------------------------
    def _customer_summary(self, customer: dict[str, Any]) -> str:
        cid = entity_id(customer, "customer_id")
        return (
            f"Customer found: {customer_name(customer)} (id {cid}), "
            f"channel={first_present(customer, ('channel', 'customer_channel'), 'unknown')}, "
            f"city={first_present(customer, ('city', 'town'), 'unknown')}, "
            f"status={first_present(customer, ('status',), 'unknown')}."
        )

    def find_customer(self, query: str = "") -> str:
        query = (query or "").strip()
        self._add("crm/customers")
        if not query:
            return "No customer query provided."
        match = re.search(r"CUST-\d{4}", query, re.IGNORECASE)
        if match:
            customer = _unwrap(self.api.crm_customer(match.group(0).upper()))
            if customer:
                return self._customer_summary(customer)
            return f"No customer with id {match.group(0).upper()} exists in the CRM."
        matches = self.api.crm_customers(search=query)
        if not matches:
            compact = re.sub(r"\b(s\.?p\.?a\.?|s\.?r\.?l\.?)\b", "", query, flags=re.IGNORECASE).strip()
            if compact and compact != query:
                matches = self.api.crm_customers(search=compact)
        if not matches:
            return f'No customer matching "{query}" exists in the CRM.'
        return self._customer_summary(matches[0])

    def customer_open_opportunities(self, customer_id: str = "", stages: list[str] | None = None) -> str:
        self._add("crm/opportunities")
        if not customer_id:
            return "A customer_id is required (resolve the customer first)."
        stages = stages or ["qualification", "negotiation"]
        opportunities: list[dict[str, Any]] = []
        for stage in stages:
            opportunities.extend(self.api.crm_opportunities(customer_id=customer_id, stage=stage))
        total = sum(opportunity_value(row) for row in opportunities)
        if not opportunities:
            return f"No open opportunities (stages {', '.join(stages)}) for {customer_id}."
        items = "; ".join(
            f"{first_present(row, ('name', 'title', 'description'), 'opportunity')} ({money(opportunity_value(row))})"
            for row in opportunities
        )
        return (
            f"{len(opportunities)} open opportunities (stages {', '.join(stages)}) "
            f"totaling {money(total)}. Items: {items}."
        )

    def opportunities_by_channel(self, stage: str = "negotiation") -> str:
        self._add("crm/opportunities", "crm/customers")
        opportunities = self.api.crm_opportunities(stage=stage)
        channel_by_id: dict[str, str] = {}
        for customer in self.api.crm_customers():
            cid = entity_id(customer, "customer_id")
            if cid:
                channel_by_id[cid] = str(first_present(customer, ("channel", "customer_channel"), "unknown"))
        totals: dict[str, float] = {}
        counts: dict[str, int] = {}
        for opportunity in opportunities:
            cid = str(first_present(opportunity, ("customer_id", "customer"), ""))
            channel = channel_by_id.get(cid, "unknown")
            totals[channel] = totals.get(channel, 0.0) + opportunity_value(opportunity)
            counts[channel] = counts.get(channel, 0) + 1
        if not totals:
            return f"No opportunities in the {stage} stage."
        parts = [
            f"{channel}: {money(totals[channel])} ({counts[channel]} opportunities)"
            for channel in sorted(totals, key=lambda key: totals[key], reverse=True)
        ]
        return f"Opportunities in the {stage} stage by customer channel: " + "; ".join(parts) + "."

    def customer_order_status(self, customer_id: str = "") -> str:
        self._add("crm/orders")
        if not customer_id:
            return "A customer_id is required (resolve the customer first)."
        orders = self.api.crm_orders(customer_id=customer_id)
        latest = latest_row(orders)
        if not latest:
            return f"No CRM orders found for {customer_id}."
        return (
            f"Latest order for {customer_id}: {entity_id(latest, 'order_id')} "
            f"with status {first_present(latest, ('status',), 'unknown')} "
            f"({len(orders)} orders total)."
        )

    # --- Calls -----------------------------------------------------------
    def latest_call_complaint(self, customer_id: str = "") -> str:
        self._add("calls")
        if not customer_id:
            return "A customer_id is required (resolve the customer first)."
        calls = self.api.calls(customer_id=customer_id)
        latest = latest_row(calls)
        if not latest:
            return f"No recorded calls found for {customer_id}."
        call_id = entity_id(latest, "call_id")
        summary = str(first_present(latest, ("summary", "topic", "notes"), ""))
        lot = str(first_present(latest, ("related_lot_id", "lot_id"), ""))
        lot_match = re.search(r"LOT-\d{4}-\d{4}", summary)
        if not lot and lot_match:
            lot = lot_match.group(0)
        defect = _defect_from_text(summary)
        if defect == "a reported defect" and call_id:
            transcript = self.api.transcript(call_id, search="broken", limit=10)
            text = " ".join(
                str(seg.get("text", "")) for seg in (transcript.get("segments") or []) if isinstance(seg, dict)
            )
            if text:
                self._add(f"calls/{call_id}/transcript")
                defect = _defect_from_text(text)
                if not lot:
                    lot_match = re.search(r"LOT-\d{4}-\d{4}", text)
                    if lot_match:
                        lot = lot_match.group(0)
        date = first_present(latest, ("started_at", "date", "call_date"), "unknown date")
        return (
            f"Last call {call_id} ({date}): complaint for {defect}, "
            f"lot {lot or 'not specified'}. Summary: {summary or 'n/a'}."
        )

    def count_calls_with_defect(self, defect: str = "broken pasta") -> str:
        self._add("calls")
        defect = (defect or "broken pasta").strip()
        calls = self.api.calls()
        count = 0
        for call in calls:
            call_id = entity_id(call, "call_id")
            if not call_id:
                continue
            transcript = self.api.transcript(call_id, search=defect, limit=1)
            if transcript.get("segments"):
                count += 1
        self._add("calls/{id}/transcript")
        return f"{count} of {len(calls)} recorded calls report a '{defect}' defect."

    # --- ERP -------------------------------------------------------------
    def inventory_status(self, sku: str = "") -> str:
        self._add("erp/inventory")
        sku = (sku or "").strip().upper()
        if not sku:
            return "A SKU is required."
        rows = self.api.inventory(search=sku)
        item = next((row for row in rows if sku in json.dumps(row).upper()), rows[0] if rows else None)
        if not item:
            return f"SKU {sku} was not found in ERP inventory."
        on_hand, minimum = inventory_quantities(item)
        flag = "below minimum stock" if is_below_min(item) else "not below minimum stock"
        return (
            f"Inventory for {sku}: on-hand {on_hand:g} cartons, minimum {minimum:g}; it is {flag}."
        )

    def bom_supplier(self, sku: str = "", component: str = "semolina") -> str:
        self._add("erp/bom")
        sku = (sku or "").strip().upper()
        component = (component or "semolina").strip().lower()
        if not sku:
            return "A finished-product SKU is required."
        bom_rows = self.api.bom(sku=sku)
        components: list[dict[str, Any]] = []
        for row in bom_rows:
            comps = row.get("components")
            if isinstance(comps, list):
                components.extend(comps)
        if not components and bom_rows:
            components = bom_rows
        match = next(
            (c for c in components if component in json.dumps(c).lower() or "RAW-SEM" in json.dumps(c).upper()),
            None,
        )
        if not match:
            return f"No '{component}' component was found in the bill of materials for {sku}."
        raw_sku = str(
            first_present(match, ("raw_sku", "raw_material_sku", "component_sku", "sku"), "")
        ).upper()
        if not raw_sku:
            raw_match = re.search(r"RAW-[A-Z]{3}-\d{3}", json.dumps(match).upper())
            raw_sku = raw_match.group(0) if raw_match else ""
        raw_name = str(first_present(match, ("description", "product_name", "name"), raw_sku))
        self._add("erp/inventory")
        inventory = self.api.inventory(search=raw_sku) if raw_sku else []
        item = next((r for r in inventory if str(r.get("sku", "")).upper() == raw_sku), inventory[0] if inventory else {})
        supplier_id = str(first_present(item, ("supplier_id",), first_present(match, ("supplier_id",), "")))
        supplier_label = supplier_id or "an unlisted supplier"
        if supplier_id:
            self._add("erp/suppliers")
            for supplier in self.api.suppliers():
                if entity_id(supplier, "supplier_id") == supplier_id:
                    supplier_label = str(first_present(supplier, ("name", "supplier_name"), supplier_id))
                    break
        flag = "is below minimum stock" if item and is_below_min(item) else "is not below minimum stock"
        return f"{sku} uses {raw_sku} ({raw_name}), supplied by {supplier_label}; the raw material {flag}."

    # --- Knowledge base --------------------------------------------------
    def kb_search(self, query: str = "") -> str:
        query = (query or "").strip()
        if not query:
            return "A search query is required."
        docs = search_kb(query, limit=3)
        if not docs:
            return "No matching documents were found in the knowledge base."
        for doc in docs:
            self._add(doc.doc_id)
        return "\n\n".join(f"{doc.doc_id} - {doc.title}\n{doc.text[:1200]}" for doc in docs)

    def kb_spec(self, sku: str = "") -> str:
        sku = (sku or "").strip().upper()
        doc = find_doc_by_sku(sku) if sku else None
        if doc is None:
            hits = search_kb(sku or "product specification", limit=1)
            doc = hits[0] if hits else None
        if doc is None:
            return "No matching product specification was found in the knowledge base."
        self._add(doc.doc_id)
        spec = extract_spec_answer(doc)
        return spec or f"{doc.doc_id} ({doc.title}) does not contain shelf-life/allergen fields."

    def kb_price(self, sku: str = "") -> str:
        sku = (sku or "").strip().upper()
        docs = search_kb((sku + " wholesale price list 2026").strip(), limit=5)
        price_doc = next((doc for doc in docs if doc.doc_id == "DOC-015"), None)
        if price_doc is None and sku:
            price_doc = find_doc_by_sku(sku)
        if price_doc is None:
            return "The official list price was not found in the knowledge base."
        self._add(price_doc.doc_id)
        if sku:
            price = extract_price(price_doc, sku)
            if price:
                return (
                    f"{price} EUR per carton for {sku}, from the official 2026 wholesale price list "
                    f"({price_doc.doc_id}), which is authoritative over figures quoted in calls."
                )
        return f"See {price_doc.doc_id} ({price_doc.title}); no exact price row was matched for {sku or 'the SKU'}."

    # --- dispatch --------------------------------------------------------
    def dispatch(self, name: str, args: dict[str, Any]) -> str:
        method = getattr(self, name, None)
        if method is None or name == "dispatch" or name.startswith("_"):
            return f"unknown_tool: {name}"
        try:
            return method(**args)
        except TypeError:
            return f"tool_error: bad arguments for {name}"


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "find_customer",
            "description": (
                "Resolve a customer by name or CUST-#### id. Use this first to verify a "
                "customer exists and to get its customer_id. Returns 'No customer ...' if absent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Customer name or CUST-#### id"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "customer_open_opportunities",
            "description": "Count and total the open opportunities (qualification + negotiation) for a customer_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "CUST-#### id"},
                    "stages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional stages; defaults to qualification and negotiation",
                    },
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opportunities_by_channel",
            "description": "Total and count opportunities in a given stage, grouped by customer channel (GDO/distributor/horeca).",
            "parameters": {
                "type": "object",
                "properties": {
                    "stage": {
                        "type": "string",
                        "description": "qualification | negotiation | won | lost (default negotiation)",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "customer_order_status",
            "description": "Return the latest order and its status for a customer_id.",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string", "description": "CUST-#### id"}},
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "latest_call_complaint",
            "description": "Return the most recent call for a customer_id with its complaint defect and related lot.",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string", "description": "CUST-#### id"}},
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_calls_with_defect",
            "description": "Page through ALL calls and count how many report a given defect (e.g. 'broken pasta').",
            "parameters": {
                "type": "object",
                "properties": {"defect": {"type": "string", "description": "Defect phrase to count"}},
                "required": ["defect"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inventory_status",
            "description": "Report on-hand quantity, minimum stock, and below-minimum flag for a SKU (finished or raw).",
            "parameters": {
                "type": "object",
                "properties": {"sku": {"type": "string", "description": "PAS-XXX-### or RAW-XXX-### SKU"}},
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bom_supplier",
            "description": "For a finished SKU, find a raw-material component (default semolina), its supplier, and stock status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "description": "Finished-product PAS-XXX-### SKU"},
                    "component": {"type": "string", "description": "Component to look up (default semolina)"},
                },
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "Search the knowledge base (specs, policies, capitolati, price list) and return the top documents.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to look for"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_spec",
            "description": "Get shelf life (TMC) and declared allergens for a finished product SKU from its spec sheet.",
            "parameters": {
                "type": "object",
                "properties": {"sku": {"type": "string", "description": "PAS-XXX-### SKU"}},
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_price",
            "description": "Get the authoritative list price for a SKU from the official 2026 wholesale price list (DOC-015).",
            "parameters": {
                "type": "object",
                "properties": {"sku": {"type": "string", "description": "PAS-XXX-### SKU"}},
                "required": ["sku"],
            },
        },
    },
]
