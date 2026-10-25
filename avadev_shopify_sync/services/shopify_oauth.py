# -*- coding: utf-8 -*-
"""OAuth authorization-code helpers for standalone Shopify apps."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import requests

from .hmac_utils import is_valid_shop_domain, verify_oauth_query_hmac

# Re-export for controllers
verify_oauth_query_hmac_safe = verify_oauth_query_hmac

_logger = logging.getLogger(__name__)

DEFAULT_SCOPES = "read_orders"
TOKEN_TIMEOUT = 30


def build_authorize_url(
    shop: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: str = DEFAULT_SCOPES,
) -> str:
    shop = _normalize_shop(shop)
    params = {
        "client_id": client_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"


def exchange_code_for_token(
    shop: str,
    client_id: str,
    client_secret: str,
    code: str,
) -> dict[str, Any]:
    shop = _normalize_shop(shop)
    url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }
    resp = requests.post(url, json=payload, timeout=TOKEN_TIMEOUT)
    if resp.status_code >= 400:
        _logger.warning(
            "Shopify token exchange failed shop=%s status=%s body=%s",
            shop,
            resp.status_code,
            resp.text[:500],
        )
        resp.raise_for_status()
    return resp.json()


def validate_oauth_callback(
    query: dict[str, str],
    client_secret: str,
    expected_state: str | None,
) -> tuple[bool, str]:
    shop = (query.get("shop") or "").strip().lower()
    if not is_valid_shop_domain(shop):
        return False, "invalid shop domain"
    state = query.get("state") or ""
    if expected_state and state != expected_state:
        return False, "invalid state"
    if not verify_oauth_query_hmac(query, client_secret):
        return False, "invalid oauth hmac"
    if not query.get("code"):
        return False, "missing code"
    return True, ""


def _normalize_shop(shop: str) -> str:
    shop = (shop or "").strip().lower()
    shop = shop.replace("https://", "").replace("http://", "").rstrip("/")
    if not shop.endswith(".myshopify.com") and "." not in shop:
        shop = f"{shop}.myshopify.com"
    return shop
