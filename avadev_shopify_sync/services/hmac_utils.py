# -*- coding: utf-8 -*-
"""HMAC helpers for Shopify OAuth query and webhook body verification."""
from __future__ import annotations

import hashlib
import hmac
from typing import Mapping
from urllib.parse import urlencode


def verify_webhook_hmac(raw_body: bytes, hmac_header: str, client_secret: str) -> bool:
    """Verify X-Shopify-Hmac-SHA256 against the raw request body."""
    if not hmac_header or not client_secret:
        return False
    digest = hmac.new(
        client_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    import base64

    calculated = base64.b64encode(digest)
    try:
        provided = hmac_header.encode("utf-8") if isinstance(hmac_header, str) else hmac_header
        return hmac.compare_digest(calculated, provided)
    except (TypeError, ValueError):
        return False


def verify_oauth_query_hmac(query: Mapping[str, str], client_secret: str) -> bool:
    """Verify the hmac query parameter on OAuth callbacks (authorization code grant)."""
    if not client_secret:
        return False
    received = query.get("hmac")
    if not received:
        return False
    params = {k: v for k, v in query.items() if k != "hmac"}
    message = urlencode(sorted(params.items())).encode("utf-8")
    digest = hmac.new(
        client_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    try:
        return hmac.compare_digest(digest, received)
    except (TypeError, ValueError):
        return False


def is_valid_shop_domain(shop: str) -> bool:
    if not shop:
        return False
    shop = shop.strip().lower()
    import re

    return bool(re.match(r"^[a-z0-9][a-z0-9\-]*\.myshopify\.com$", shop))
