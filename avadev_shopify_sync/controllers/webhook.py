# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AvadevShopifyWebhookController(http.Controller):
    @http.route(
        "/avadev_shopify/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def shopify_webhook(self, **kwargs):
        raw = request.httprequest.get_data()
        headers = request.httprequest.headers
        hmac_header = headers.get("X-Shopify-Hmac-SHA256") or ""
        topic = headers.get("X-Shopify-Topic") or ""
        webhook_id = headers.get("X-Shopify-Webhook-Id") or ""
        shop_domain = (headers.get("X-Shopify-Shop-Domain") or "").strip().lower()

        Account = request.env["shopify.account"].sudo()
        account = Account.find_by_shop(shop_domain) if shop_domain else Account.browse()
        if not account:
            accounts = Account.search(
                [("active", "=", True), ("client_secret", "!=", False)]
            )
            for cand in accounts:
                if cand.verify_webhook_hmac(raw, hmac_header):
                    account = cand
                    break

        if not account:
            _logger.warning("Webhook: no account for shop=%s", shop_domain)
            return request.make_json_response({"error": "unknown shop"}, status=401)

        if not account.verify_webhook_hmac(raw, hmac_header):
            _logger.warning("Webhook HMAC failed shop=%s topic=%s", shop_domain, topic)
            return request.make_json_response({"error": "unauthorized"}, status=401)

        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return request.make_json_response({"error": "invalid payload"}, status=400)

        order_id = str(payload.get("id") or "")
        Event = request.env["shopify.webhook.event"].sudo()
        Event.enqueue(
            account=account,
            webhook_id=webhook_id,
            topic=topic,
            shop_domain=shop_domain or account.shop_domain,
            shopify_order_id=order_id,
            payload=payload,
        )
        return request.make_json_response({"status": "ok"})
