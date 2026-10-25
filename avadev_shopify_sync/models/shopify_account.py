# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.avadev_shopify_sync.services import shopify_oauth
from odoo.addons.avadev_shopify_sync.services.hmac_utils import (
    is_valid_shop_domain,
    verify_webhook_hmac,
)
from odoo.addons.avadev_shopify_sync.services.shopify_client import (
    DEFAULT_API_VERSION,
    ShopifyClient,
    ShopifyClientError,
)

_logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/avadev_shopify/webhook"
INSTALL_PATH = "/avadev_shopify/install"
CALLBACK_PATH = "/avadev_shopify/oauth/callback"


class ShopifyAccount(models.Model):
    _name = "shopify.account"
    _description = "Shopify store account"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, default="Shopify")
    active = fields.Boolean(default=True)
    shop_domain = fields.Char(
        required=True,
        help="Store domain, e.g. avadev-test.myshopify.com",
        tracking=True,
    )
    client_id = fields.Char(string="Client ID", required=True)
    client_secret = fields.Char(string="Client Secret", required=True)
    access_token = fields.Char(string="Access Token")
    api_version = fields.Char(default=DEFAULT_API_VERSION, required=True)
    webhook_public_base_url = fields.Char(
        string="Public Base URL (ngrok)",
        help="HTTPS base without trailing slash, e.g. https://xxx.ngrok-free.dev",
    )
    scopes = fields.Char(default="read_orders")
    oauth_connected = fields.Boolean(readonly=True)
    oauth_state = fields.Char(copy=False)
    last_order_sync_at = fields.Datetime(
        string="Last Order Sync",
        help="Cursor for incremental order pull (updated_at_min).",
    )
    webhook_registered = fields.Boolean(readonly=True)
    webhook_callback_url = fields.Char(compute="_compute_webhook_callback_url")
    order_mirror_count = fields.Integer(compute="_compute_counts")
    webhook_event_count = fields.Integer(compute="_compute_counts")

    _shop_domain_uniq = models.Constraint(
        "unique(shop_domain)",
        "Shop domain must be unique.",
    )

    @api.depends("webhook_public_base_url")
    def _compute_webhook_callback_url(self):
        for rec in self:
            base = (rec.webhook_public_base_url or "").rstrip("/")
            rec.webhook_callback_url = f"{base}{WEBHOOK_PATH}" if base else ""

    def _compute_counts(self):
        Mirror = self.env["shopify.order.mirror"]
        Event = self.env["shopify.webhook.event"]
        for rec in self:
            rec.order_mirror_count = Mirror.search_count([("account_id", "=", rec.id)])
            rec.webhook_event_count = Event.search_count([("account_id", "=", rec.id)])

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("shop_domain"):
                vals["shop_domain"] = self._normalize_shop_domain(vals["shop_domain"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("shop_domain"):
            vals["shop_domain"] = self._normalize_shop_domain(vals["shop_domain"])
        return super().write(vals)

    @api.model
    def _normalize_shop_domain(self, shop: str) -> str:
        shop = (shop or "").strip().lower()
        shop = shop.replace("https://", "").replace("http://", "").rstrip("/")
        if shop and not shop.endswith(".myshopify.com") and "." not in shop:
            shop = f"{shop}.myshopify.com"
        if shop and not is_valid_shop_domain(shop):
            raise UserError(_("Invalid shop domain: %s") % shop)
        return shop

    def _public_base_url(self) -> str:
        self.ensure_one()
        base = (self.webhook_public_base_url or "").rstrip("/")
        if not base:
            raise UserError(
                _("Set Public Base URL (ngrok) on the Shopify account first.")
            )
        return base

    def _callback_url(self) -> str:
        return f"{self._public_base_url()}{CALLBACK_PATH}"

    def _install_url(self) -> str:
        return f"{self._public_base_url()}{INSTALL_PATH}"

    def _shopify_client(self) -> ShopifyClient:
        self.ensure_one()
        if not self.access_token:
            raise UserError(_("Missing access token. Connect with Shopify OAuth first."))
        return ShopifyClient(
            shop=self.shop_domain,
            access_token=self.access_token,
            api_version=self.api_version or DEFAULT_API_VERSION,
        )

    def verify_webhook_hmac(self, raw_body: bytes, hmac_header: str) -> bool:
        self.ensure_one()
        return verify_webhook_hmac(raw_body, hmac_header or "", self.client_secret or "")

    def action_open_oauth_connect(self):
        """Open install URL so Shopify can complete OAuth via ngrok."""
        self.ensure_one()
        state = secrets.token_urlsafe(24)
        self.oauth_state = state
        base = self._public_base_url()
        # Prefer direct authorize URL so Connect works even if App URL is wrong
        url = shopify_oauth.build_authorize_url(
            shop=self.shop_domain,
            client_id=self.client_id,
            redirect_uri=self._callback_url(),
            state=state,
            scopes=self.scopes or "read_orders",
        )
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }

    def action_test_connection(self):
        self.ensure_one()
        try:
            shop = self._shopify_client().get_shop()
        except ShopifyClientError as exc:
            raise UserError(_("Connection failed: %s") % exc) from exc
        name = shop.get("name") or shop.get("myshopify_domain") or self.shop_domain
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Shopify"),
                "message": _("Connected to shop: %s") % name,
                "type": "success",
                "sticky": False,
            },
        }

    def action_register_webhooks(self):
        self.ensure_one()
        address = self.webhook_callback_url
        if not address:
            raise UserError(_("Set Public Base URL before registering webhooks."))
        try:
            ensured = self._shopify_client().ensure_order_webhooks(address)
        except ShopifyClientError as exc:
            raise UserError(_("Webhook registration failed: %s") % exc) from exc
        self.webhook_registered = True
        self.message_post(
            body=_("Registered %s webhook(s) at %s") % (len(ensured), address)
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Shopify"),
                "message": _("Webhooks registered: %s") % len(ensured),
                "type": "success",
                "sticky": False,
            },
        }

    def action_sync_orders_now(self):
        self.ensure_one()
        count = self._sync_orders()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Shopify"),
                "message": _("Synced %s order(s)") % count,
                "type": "success",
                "sticky": False,
            },
        }

    def _sync_orders(self) -> int:
        self.ensure_one()
        client = self._shopify_client()
        updated_at_min = None
        if self.last_order_sync_at:
            # Shopify expects ISO-8601; Odoo datetime is naive UTC in practice
            dt = fields.Datetime.to_datetime(self.last_order_sync_at)
            updated_at_min = dt.replace(tzinfo=timezone.utc).isoformat()

        synced = 0
        since_id = None
        max_updated = self.last_order_sync_at
        Mirror = self.env["shopify.order.mirror"]
        while True:
            orders = client.list_orders(
                updated_at_min=updated_at_min,
                since_id=since_id,
                limit=50,
            )
            if not orders:
                break
            for order in orders:
                Mirror.upsert_from_shopify_order(self, order)
                synced += 1
                since_id = order.get("id") or since_id
                raw_updated = order.get("updated_at")
                if raw_updated:
                    try:
                        # e.g. 2024-10-01T10:20:39-04:00
                        parsed = datetime.fromisoformat(raw_updated.replace("Z", "+00:00"))
                        naive = parsed.astimezone(timezone.utc).replace(tzinfo=None)
                        if not max_updated or naive > fields.Datetime.to_datetime(max_updated):
                            max_updated = naive
                    except ValueError:
                        pass
            if len(orders) < 50:
                break

        vals = {"last_order_sync_at": max_updated or fields.Datetime.now()}
        self.write(vals)
        return synced

    @api.model
    def _cron_sync_orders(self):
        accounts = self.search([("active", "=", True), ("access_token", "!=", False)])
        for account in accounts:
            try:
                account._sync_orders()
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Order pull failed for shopify.account %s", account.id
                )

    def complete_oauth(self, code: str, shop: str):
        self.ensure_one()
        data = shopify_oauth.exchange_code_for_token(
            shop=shop or self.shop_domain,
            client_id=self.client_id,
            client_secret=self.client_secret,
            code=code,
        )
        token = data.get("access_token")
        if not token:
            raise UserError(_("Shopify did not return an access_token."))
        self.write(
            {
                "access_token": token,
                "oauth_connected": True,
                "oauth_state": False,
                "scopes": data.get("scope") or self.scopes,
            }
        )
        self.message_post(body=_("OAuth completed; access token stored."))
        return True

    @api.model
    def find_by_shop(self, shop: str):
        shop = (shop or "").strip().lower()
        shop = shop.replace("https://", "").replace("http://", "").rstrip("/")
        if shop and not shop.endswith(".myshopify.com") and "." not in shop:
            shop = f"{shop}.myshopify.com"
        if not shop or not is_valid_shop_domain(shop):
            return self.browse()
        return self.search([("shop_domain", "=", shop)], limit=1)
