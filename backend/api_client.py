"""Thin client for the Al Dente mock APIs."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx


class ApiError(RuntimeError):
    """Raised when an upstream mock API request fails."""


class AlDenteApiClient:
    def __init__(self) -> None:
        # Accept both the documented names (MOCK_API_*) and the local .env
        # names (ALDENTE_API_*) so the same code runs locally and on Railway.
        self.base_url = (
            os.getenv("MOCK_API_BASE_URL")
            or os.getenv("ALDENTE_API_BASE_URL")
            or "https://aldente.yellowtest.it"
        ).rstrip("/")
        self.token = os.getenv("MOCK_API_TOKEN") or os.getenv("ALDENTE_API_KEY") or ""
        self.timeout = httpx.Timeout(8.0, connect=4.0)

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise ApiError("MOCK_API_TOKEN is not configured")
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        clean_params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        last_exc: Exception | None = None
        # One retry: transient timeouts/transport errors should not break /ask.
        for attempt in range(2):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.get(url, headers=self._headers(), params=clean_params)
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                # 4xx are deterministic; do not retry.
                if status < 500:
                    raise ApiError(f"API request failed: {path} returned {status}") from exc
                last_exc = exc
            except (httpx.TimeoutException, httpx.TransportError, ValueError) as exc:
                last_exc = exc
            if attempt == 0:
                time.sleep(0.4)
        raise ApiError(f"API request failed: {path}") from last_exc

    def list_all(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int = 200,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        safe_limit = min(max(limit, 1), 200)
        for _ in range(max_pages):
            page = self.get(path, {**(params or {}), "limit": safe_limit, "offset": offset})
            data = page.get("data", [])
            if isinstance(data, list):
                rows.extend(data)
            pagination = page.get("pagination") or {}
            total = int(pagination.get("total") or len(rows))
            offset += safe_limit
            if offset >= total or not data:
                break
        return rows

    def transcript(
        self,
        call_id: str,
        *,
        search: str | None = None,
        speaker: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.get(
            f"/calls/{call_id}/transcript",
            {"search": search, "speaker": speaker, "limit": min(limit, 200), "offset": 0},
        )

    def crm_customers(self, **params: Any) -> list[dict[str, Any]]:
        return self.list_all("/crm/customers", params)

    def crm_customer(self, customer_id: str) -> dict[str, Any]:
        return self.get(f"/crm/customers/{customer_id}")

    def crm_opportunities(self, **params: Any) -> list[dict[str, Any]]:
        return self.list_all("/crm/opportunities", params)

    def crm_orders(self, **params: Any) -> list[dict[str, Any]]:
        return self.list_all("/crm/orders", params)

    def calls(self, **params: Any) -> list[dict[str, Any]]:
        return self.list_all("/calls", params)

    def call(self, call_id: str) -> dict[str, Any]:
        return self.get(f"/calls/{call_id}")

    def production_orders(self, **params: Any) -> list[dict[str, Any]]:
        return self.list_all("/erp/production-orders", params)

    def inventory(self, **params: Any) -> list[dict[str, Any]]:
        return self.list_all("/erp/inventory", params)

    def suppliers(self, **params: Any) -> list[dict[str, Any]]:
        return self.list_all("/erp/suppliers", params)

    def bom(self, **params: Any) -> list[dict[str, Any]]:
        return self.list_all("/erp/bom", params)

    def shipments(self, **params: Any) -> list[dict[str, Any]]:
        return self.list_all("/erp/shipments", params)
