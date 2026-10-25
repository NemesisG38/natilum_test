# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import secrets

from odoo import http
from odoo.http import request
from odoo.addons.avadev_shopify_sync.services import shopify_oauth
from odoo.addons.avadev_shopify_sync.services.hmac_utils import (
    is_valid_shop_domain,
    verify_oauth_query_hmac,
)

_logger = logging.getLogger(__name__)


class AvadevShopifyOAuthController(http.Controller):
    @http.route(
        "/avadev_shopify/install",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=True,
    )
    def shopify_install(self, **kwargs):
        shop = (kwargs.get("shop") or "").strip().lower()
        shop = shop.replace("https://", "").replace("http://", "").rstrip("/")
        if shop and not shop.endswith(".myshopify.com") and "." not in shop:
            shop = f"{shop}.myshopify.com"

        Account = request.env["shopify.account"].sudo()
        account = Account.find_by_shop(shop) if shop else Account.browse()
        if not account:
            accounts = Account.search([("active", "=", True)], limit=2)
            if len(accounts) == 1:
                account = accounts

        if not account:
            return request.make_response(
                "<h1>Shopify install</h1>"
                "<p>No matching shopify.account in Odoo. "
                "Create one with this shop domain, client id and secret first.</p>",
                headers=[("Content-Type", "text/html; charset=utf-8")],
                status=400,
            )

        if shop and is_valid_shop_domain(shop) and kwargs.get("hmac"):
            query = {k: (v if isinstance(v, str) else str(v)) for k, v in kwargs.items()}
            if not verify_oauth_query_hmac(query, account.client_secret):
                _logger.warning("Install request HMAC mismatch for shop=%s", shop)

        state = secrets.token_urlsafe(24)
        account.oauth_state = state
        try:
            redirect_uri = f"{account._public_base_url()}/avadev_shopify/oauth/callback"
        except Exception:  # noqa: BLE001
            return request.make_response(
                "<h1>Shopify install</h1>"
                "<p>Set Public Base URL (ngrok) on the Shopify account in Odoo.</p>",
                headers=[("Content-Type", "text/html; charset=utf-8")],
                status=400,
            )

        url = shopify_oauth.build_authorize_url(
            shop=account.shop_domain,
            client_id=account.client_id,
            redirect_uri=redirect_uri,
            state=state,
            scopes=account.scopes or "read_orders",
        )
        return request.redirect(url, local=False)

    @http.route(
        "/avadev_shopify/oauth/callback",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=True,
    )
    def shopify_oauth_callback(self, **kwargs):
        query = {k: (v if isinstance(v, str) else str(v)) for k, v in kwargs.items()}
        shop = (query.get("shop") or "").strip().lower()
        Account = request.env["shopify.account"].sudo()
        account = Account.find_by_shop(shop)
        if not account:
            return request.make_response(
                "<h1>OAuth callback</h1><p>Unknown shop.</p>",
                headers=[("Content-Type", "text/html; charset=utf-8")],
                status=400,
            )

        ok, reason = shopify_oauth.validate_oauth_callback(
            query,
            account.client_secret,
            expected_state=account.oauth_state,
        )
        if not ok:
            _logger.warning("OAuth callback rejected: %s", reason)
            return request.make_response(
                f"<h1>OAuth callback</h1><p>Rejected: {reason}</p>",
                headers=[("Content-Type", "text/html; charset=utf-8")],
                status=403,
            )

        try:
            account.complete_oauth(code=query["code"], shop=shop)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("OAuth token exchange failed")
            return request.make_response(
                f"<h1>OAuth callback</h1><p>Token exchange failed: {exc}</p>",
                headers=[("Content-Type", "text/html; charset=utf-8")],
                status=500,
            )

        backend = request.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        return request.make_response(
            "<h1>Shopify connected</h1>"
            "<p>Access token stored in Odoo. You can close this window.</p>"
            f'<p><a href="{backend}">Open Odoo</a></p>',
            headers=[("Content-Type", "text/html; charset=utf-8")],
        )
