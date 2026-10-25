# -*- coding: utf-8 -*-
"""Minimal Shopify Admin REST client (orders + webhooks)."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import requests

_logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "2024-10"
REQUEST_TIMEOUT = 30
WEBHOOK_TOPICS = ("orders/create", "orders/updated")


class ShopifyClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ShopifyClient:
    def __init__(
        self,
        shop: str,
        access_token: str,
        api_version: str = DEFAULT_API_VERSION,
        session: requests.Session | None = None,
    ):
        self.shop = _normalize_shop(shop)
        self.access_token = access_token
        self.api_version = api_version or DEFAULT_API_VERSION
        self.session = session or requests.Session()

    @property
    def base_url(self) -> str:
        return f"https://{self.shop}/admin/api/{self.api_version}/"

    def _headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = urljoin(self.base_url, path.lstrip("/"))
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        kwargs.setdefault("headers", self._headers())
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code >= 400:
            _logger.warning(
                "Shopify API error %s %s status=%s body=%s",
                method,
                path,
                resp.status_code,
                resp.text[:500],
            )
            raise ShopifyClientError(
                f"Shopify API {method} {path} failed ({resp.status_code})",
                status_code=resp.status_code,
                body=resp.text[:2000],
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def get_shop(self) -> dict[str, Any]:
        data = self._request("GET", "shop.json")
        return (data or {}).get("shop") or {}

    def get_order(self, order_id: int | str) -> dict[str, Any]:
        data = self._request("GET", f"orders/{order_id}.json")
        return (data or {}).get("order") or {}

    def list_orders(
        self,
        *,
        updated_at_min: str | None = None,
        status: str = "any",
        limit: int = 50,
        since_id: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"status": status, "limit": min(limit, 250)}
        if updated_at_min:
            params["updated_at_min"] = updated_at_min
        if since_id:
            params["since_id"] = since_id
        data = self._request("GET", "orders.json", params=params)
        return (data or {}).get("orders") or []

    def list_webhooks(self) -> list[dict[str, Any]]:
        data = self._request("GET", "webhooks.json")
        return (data or {}).get("webhooks") or []

    def create_webhook(self, topic: str, address: str, fmt: str = "json") -> dict[str, Any]:
        payload = {
            "webhook": {
                "topic": topic,
                "address": address,
                "format": fmt,
            }
        }
        data = self._request("POST", "webhooks.json", json=payload)
        return (data or {}).get("webhook") or {}

    def delete_webhook(self, webhook_id: int | str) -> None:
        self._request("DELETE", f"webhooks/{webhook_id}.json")

    def ensure_order_webhooks(self, callback_address: str) -> list[dict[str, Any]]:
        """Idempotently ensure orders/create and orders/updated point to address."""
        existing = self.list_webhooks()
        by_topic: dict[str, list[dict]] = {}
        for wh in existing:
            by_topic.setdefault(wh.get("topic") or "", []).append(wh)

        ensured: list[dict[str, Any]] = []
        for topic in WEBHOOK_TOPICS:
            matches = [
                w
                for w in by_topic.get(topic, [])
                if (w.get("address") or "").rstrip("/") == callback_address.rstrip("/")
            ]
            if matches:
                ensured.append(matches[0])
                continue
            # Remove stale same-topic webhooks with different address (dev ngrok churn)
            for stale in by_topic.get(topic, []):
                try:
                    self.delete_webhook(stale["id"])
                except ShopifyClientError:
                    _logger.exception("Failed deleting stale webhook %s", stale.get("id"))
            ensured.append(self.create_webhook(topic, callback_address))
        return ensured


def _normalize_shop(shop: str) -> str:
    shop = (shop or "").strip().lower()
    shop = shop.replace("https://", "").replace("http://", "").rstrip("/")
    if shop and not shop.endswith(".myshopify.com") and "." not in shop:
        shop = f"{shop}.myshopify.com"
    return shop
