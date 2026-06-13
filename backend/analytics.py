"""Deterministic helpers for evaluator-style calculations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


def first_present(row: dict[str, Any], names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return default


def as_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("EUR", "").replace("€", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def money(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,} EUR"
    return f"{value:,.2f} EUR"


def entity_id(row: dict[str, Any], *fallbacks: str) -> str:
    return str(first_present(row, ("id", *fallbacks), "")).strip()


def customer_name(row: dict[str, Any]) -> str:
    return str(
        first_present(
            row,
            ("company_name", "name", "ragione_sociale", "customer_name"),
            "the customer",
        )
    )


def product_name(row: dict[str, Any]) -> str:
    return str(first_present(row, ("product_name", "name", "description", "sku"), "the product"))


def opportunity_value(row: dict[str, Any]) -> float:
    return as_number(
        first_present(
            row,
            (
                "value",
                "amount",
                "expected_value",
                "total_value",
                "deal_value",
                "estimated_value",
                "value_eur",
            ),
        )
    )


def inventory_quantities(row: dict[str, Any]) -> tuple[float, float]:
    on_hand = as_number(
        first_present(
            row,
            ("on_hand", "on_hand_quantity", "quantity_on_hand", "available_quantity", "quantity", "stock"),
        )
    )
    minimum = as_number(first_present(row, ("minimum_stock", "min_stock", "minimum", "reorder_point")))
    return on_hand, minimum


def is_below_min(row: dict[str, Any]) -> bool:
    raw = first_present(row, ("below_min", "is_below_min", "below_minimum"))
    if isinstance(raw, bool):
        return raw
    if raw is not None:
        return str(raw).lower() in {"true", "yes", "1"}
    on_hand, minimum = inventory_quantities(row)
    return minimum > 0 and on_hand < minimum


def latest_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    def key(row: dict[str, Any]) -> tuple[str, str]:
        raw = str(first_present(row, ("started_at", "date", "created_at", "call_date", "timestamp"), ""))
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.isoformat(), entity_id(row)
        except ValueError:
            return raw, entity_id(row)

    return sorted(rows, key=key, reverse=True)[0]


def group_sum(rows: list[dict[str, Any]], key_name: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        key = str(row.get(key_name) or "unknown")
        totals[key] = totals.get(key, 0.0) + opportunity_value(row)
    return totals


def unique_sources(sources: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for source in sources:
        if source and source not in seen:
            ordered.append(source)
            seen.add(source)
    return ordered
