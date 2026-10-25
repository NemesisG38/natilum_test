# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging

from odoo import api, fields, models
from odoo.addons.avadev_shopify_sync.services.shopify_client import ShopifyClientError

_logger = logging.getLogger(__name__)


class ShopifyWebhookEvent(models.Model):
    _name = "shopify.webhook.event"
    _description = "Shopify webhook event queue"
    _order = "id desc"

    account_id = fields.Many2one(
        "shopify.account",
        ondelete="set null",
        index=True,
    )
    webhook_id = fields.Char(index=True, string="Shopify Webhook Id")
    topic = fields.Char(index=True)
    shop_domain = fields.Char()
    shopify_order_id = fields.Char(index=True)
    payload_json = fields.Text()
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("done", "Done"),
            ("error", "Error"),
            ("skipped", "Skipped"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    error_message = fields.Text()
    processed_at = fields.Datetime()

    _webhook_id_uniq = models.Constraint(
        "unique(webhook_id)",
        "Webhook delivery id must be unique.",
    )

    @api.model
    def enqueue(
        self,
        *,
        account,
        webhook_id: str,
        topic: str,
        shop_domain: str,
        shopify_order_id: str,
        payload: dict,
    ):
        if webhook_id:
            existing = self.search([("webhook_id", "=", webhook_id)], limit=1)
            if existing:
                return existing
        else:
            import uuid

            webhook_id = f"local-{uuid.uuid4().hex}"
        return self.create(
            {
                "account_id": account.id if account else False,
                "webhook_id": webhook_id,
                "topic": topic or "",
                "shop_domain": shop_domain or "",
                "shopify_order_id": shopify_order_id or "",
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "state": "pending",
            }
        )

    @api.model
    def _cron_process_queue(self, batch_size: int = 20):
        events = self.search([("state", "=", "pending")], limit=batch_size, order="id asc")
        for event in events:
            try:
                event._process_event()
            except Exception as exc:  # noqa: BLE001 — isolate queue items
                _logger.exception("Webhook event %s failed", event.id)
                event.write(
                    {
                        "state": "error",
                        "error_message": str(exc)[:2000],
                        "processed_at": fields.Datetime.now(),
                    }
                )

    def _process_event(self):
        self.ensure_one()
        account = self.account_id
        if not account:
            shop = (self.shop_domain or "").lower()
            account = self.env["shopify.account"].search(
                [("shop_domain", "=", shop)],
                limit=1,
            )
            if account:
                self.account_id = account.id
        if not account:
            self.write(
                {
                    "state": "error",
                    "error_message": "No shopify.account for shop domain",
                    "processed_at": fields.Datetime.now(),
                }
            )
            return
        if not account.access_token:
            self.write(
                {
                    "state": "error",
                    "error_message": "missing access_token",
                    "processed_at": fields.Datetime.now(),
                }
            )
            return

        order_id = self.shopify_order_id
        if not order_id and self.payload_json:
            try:
                payload = json.loads(self.payload_json)
                order_id = str(payload.get("id") or "")
            except json.JSONDecodeError:
                order_id = ""

        if not order_id:
            self.write(
                {
                    "state": "error",
                    "error_message": "missing shopify order id",
                    "processed_at": fields.Datetime.now(),
                }
            )
            return

        try:
            order = account._shopify_client().get_order(order_id)
        except ShopifyClientError as exc:
            self.write(
                {
                    "state": "error",
                    "error_message": str(exc)[:2000],
                    "processed_at": fields.Datetime.now(),
                }
            )
            return

        self.env["shopify.order.mirror"].upsert_from_shopify_order(account, order)
        self.write(
            {
                "state": "done",
                "shopify_order_id": str(order.get("id") or order_id),
                "error_message": False,
                "processed_at": fields.Datetime.now(),
            }
        )
