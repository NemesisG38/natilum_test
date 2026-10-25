# -*- coding: utf-8 -*-
{
    "name": "AVADEV Shopify Order Sync",
    "summary": "Sync Shopify orders to a mirror store via OAuth, webhooks and Admin API",
    "version": "1.0.0",
    "author": "AVADEV",
    "website": "https://www.avadev.mx",
    "category": "Sales",
    "license": "Other proprietary",
    "depends": ["base", "mail"],
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/shopify_account_views.xml",
        "views/shopify_order_mirror_views.xml",
        "views/shopify_webhook_event_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": True,
}
