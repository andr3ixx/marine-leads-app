"""Tech-stack fingerprinting against raw HTML (unchanged logic from the v1 script)."""

import re

TECH_PATTERNS: dict[str, list[str]] = {
    "WordPress":          ["wp-content/", "wp-json/", "wp-includes/"],
    "Shopify":            ["cdn.shopify.com", "shopify.com/s/files"],
    "Wix":                ["wixstatic.com", "wix-warmup-data", "_wix_browser_"],
    "Squarespace":        ["squarespace.com", "squarespace-cdn.com"],
    "Weebly":             ["weeblycloud.com", "weebly.com/files"],
    "Webflow":            ["webflow.io", "webflow.com/css"],
    "Google Tag Manager": ["googletagmanager.com/gtm.js", "gtm.start"],
    "Google Analytics":   ["google-analytics.com/analytics.js", "gtag('config'"],
    "Meta Pixel":         ["fbq('init'", "connect.facebook.net/en_US/fbevents.js"],
    "Google Ads Tag":     ["googleads.g.doubleclick.net", "google_ads_iframe"],
    "Hotjar":             ["static.hotjar.com", "hjSetting"],
    "FareHarbor":         ["fareharbor.com", "fhconf"],
    "Rezdy":              ["rezdy.com/widgets", "rezdy-widget"],
    "Bookeo":             ["bookeo.com/api", "bookeo.com/widget"],
    "Stripe":             ["js.stripe.com"],
    "HubSpot":            ["js.hs-scripts.com", "hubspot.com/beacon"],
    "Intercom":           ["widget.intercom.io", "intercomSettings"],
}


def detect_tech_stack(html: str) -> list[str]:
    found = []
    for name, patterns in TECH_PATTERNS.items():
        if any(p in html for p in patterns):
            found.append(name)
    return found


def has_booking_tool(tech: list[str]) -> bool:
    return any(t in tech for t in ("FareHarbor", "Rezdy", "Bookeo"))


def has_analytics(tech: list[str]) -> bool:
    return any(t in tech for t in ("Google Analytics", "Google Tag Manager", "Meta Pixel"))


def is_diy_builder(tech: list[str]) -> bool:
    return any(t in tech for t in ("Wix", "Weebly"))
