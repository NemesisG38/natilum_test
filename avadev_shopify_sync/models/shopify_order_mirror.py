# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from typing import Any

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ShopifyOrderMirror(models.Model):
    _name = "shopify.order.mirror"
    _description = "Shopify order mirror (external copy)"
    _order = "shopify_updated_at desc, id desc"
    _rec_name = "name"

    account_id = fields.Many2one(
        "shopify.account",
        required=True,
        ondelete="cascade",
        index=True,
    )
    shopify_order_id = fields.Char(required=True, index=True)
    name = fields.Char(index=True)
    order_number = fields.Char()
    financial_status = fields.Char()
    fulfillment_status = fields.Char()
    currency = fields.Char()
    total_price = fields.Char()
    customer_email = fields.Char()
    shopify_created_at = fields.Char()
    shopify_updated_at = fields.Char()
    cancelled_at = fields.Char()
    raw_json = fields.Text()
    line_ids = fields.One2many(
        "shopify.order.line.mirror",
        "order_id",
        string="Lines",
    )

    _shopify_order_account_uniq = models.Constraint(
        "unique(account_id, shopify_order_id)",
        "Shopify order id must be unique per account.",
    )

    @api.model
    def upsert_from_shopify_order(
        self,
        account,
        order_payload: dict[str, Any],
        *,
        store_raw: bool = True,
    ):
        """Create or update mirror + lines from Admin API order JSON."""
        if not order_payload or not order_payload.get("id"):
            return self.browse()
        shopify_id = str(order_payload["id"])
        vals = {
            "account_id": account.id,
            "shopify_order_id": shopify_id,
            "name": order_payload.get("name") or shopify_id,
            "order_number": str(order_payload.get("order_number") or ""),
            "financial_status": order_payload.get("financial_status") or "",
            "fulfillment_status": order_payload.get("fulfillment_status") or "",
            "currency": order_payload.get("currency") or "",
            "total_price": str(
                order_payload.get("current_total_price")
                or order_payload.get("total_price")
                or ""
            ),
            "customer_email": order_payload.get("email")
            or order_payload.get("contact_email")
            or "",
            "shopify_created_at": order_payload.get("created_at") or "",
            "shopify_updated_at": order_payload.get("updated_at") or "",
            "cancelled_at": order_payload.get("cancelled_at") or "",
        }
        if store_raw:
            vals["raw_json"] = json.dumps(order_payload, ensure_ascii=False)

        existing = self.search(
            [
                ("account_id", "=", account.id),
                ("shopify_order_id", "=", shopify_id),
            ],
            limit=1,
        )
        if existing:
            existing.write(vals)
            record = existing
        else:
            record = self.create(vals)

        record.line_ids.unlink()
        line_cmds = []
        for line in order_payload.get("line_items") or []:
            line_cmds.append(
                (
                    0,
                    0,
                    {
                        "shopify_line_id": str(line.get("id") or ""),
                        "sku": line.get("sku") or "",
                        "title": line.get("title") or line.get("name") or "",
                        "quantity": float(line.get("quantity") or 0),
                        "price": str(line.get("price") or ""),
                        "variant_id": str(line.get("variant_id") or ""),
                    },
                )
            )
        if line_cmds:
            record.write({"line_ids": line_cmds})
        return record


class ShopifyOrderLineMirror(models.Model):
    _name = "shopify.order.line.mirror"
    _description = "Shopify order line mirror"
    _order = "id"

    order_id = fields.Many2one(
        "shopify.order.mirror",
        required=True,
        ondelete="cascade",
        index=True,
    )
    shopify_line_id = fields.Char()
    sku = fields.Char()
    title = fields.Char()
    quantity = fields.Float()
    price = fields.Char()
    variant_id = fields.Char()
