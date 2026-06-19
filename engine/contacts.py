"""
Contact discovery.

Scans HTML from the homepage plus a small set of likely internal pages
(contact, about, team, footer-linked legal pages, booking/enquiry pages) for:
  - mailto: links
  - visible email addresses
  - obfuscated emails ("hello [at] domain [dot] com", "hello AT domain DOT com")
  - phone numbers
  - social media links
  - schema.org Organization/ContactPoint JSON-LD

Classifies each email found and produces ONE recommended contact record per
lead, with a confidence score and a flag for whether it needs manual
verification before sending. This deliberately does NOT try to replace
Hunter/Snov — it only surfaces what's already visible on the site.
"""

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Pages worth checking beyond the homepage, matched against link text/href (case-insensitive)
CONTACT_PAGE_HINTS = [
    "contact", "about", "team", "our-team", "crew", "captain",
    "book", "booking", "enquire", "enquiry", "inquiry", "reserve",
    "privacy", "legal", "terms",
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# "hello [at] domain [dot] com" / "hello (at) domain (dot) com" / "hello AT domain DOT com"
OBFUSCATED_EMAIL_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]+)\s*[\[\(]?\s*(?:at|AT)\s*[\]\)]?\s*([a-zA-Z0-9.\-]+)\s*[\[\(]?\s*(?:dot|DOT)\s*[\]\)]?\s*([a-zA-Z]{2,})"
)

PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?)?\d{2,4}[\s.\-]\d{3,4}[\s.\-]?\d{3,4}"
)

SOCIAL_DOMAINS = {
    "facebook.com": "Facebook",
    "instagram.com": "Instagram",
    "twitter.com": "Twitter/X",
    "x.com": "Twitter/X",
    "youtube.com": "YouTube",
    "tiktok.com": "TikTok",
    "linkedin.com": "LinkedIn",
}

GENERIC_LOCAL_PARTS = {"info", "hello", "hi", "contact", "admin", "office", "mail", "general"}
BOOKING_LOCAL_PARTS = {"book", "booking", "bookings", "reservations", "reserve", "enquiry", "enquiries", "inquiry", "inquiries"}
SALES_LOCAL_PARTS = {"sales", "charter", "charters", "booknow", "trips"}

PLACEHOLDER_DOMAINS = {"example.com", "yourdomain.com", "sentry.io", "wixpress.com"}


@dataclass
class EmailCandidate:
    email: str
    source_url: str
    visible_on_page: bool          # True if directly visible/mailto, False if reconstructed from obfuscation
    category: str                  # personal | generic | bookings | sales | info | risky/uncertain
    needs_verification: bool
    confidence: float              # 0.0-1.0


@dataclass
class ContactBundle:
    emails: List[EmailCandidate] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    social_links: dict = field(default_factory=dict)   # platform -> url
    contact_form_url: Optional[str] = None
    pages_scanned: List[str] = field(default_factory=list)

    @property
    def best_email(self) -> Optional[EmailCandidate]:
        if not self.emails:
            return None
        # Prefer: visible > category priority > confidence
        priority = {"bookings": 0, "sales": 1, "info": 2, "generic": 3, "personal": 4, "risky/uncertain": 5}
        return sorted(
            self.emails,
            key=lambda e: (not e.visible_on_page, priority.get(e.category, 9), -e.confidence),
        )[0]


def classify_email(email: str) -> str:
    local = email.split("@")[0].lower()
    if local in BOOKING_LOCAL_PARTS or any(local.startswith(p) for p in BOOKING_LOCAL_PARTS):
        return "bookings"
    if local in SALES_LOCAL_PARTS or any(local.startswith(p) for p in SALES_LOCAL_PARTS):
        return "sales"
    if local in GENERIC_LOCAL_PARTS:
        return "info"
    if re.fullmatch(r"[a-z]+\.?[a-z]*", local) and len(local) > 2 and local not in GENERIC_LOCAL_PARTS:
        # looks like a person's name (e.g. "sarah", "john.smith")
        return "personal"
    return "generic"


def is_plausible_email(email: str) -> bool:
    domain = email.split("@")[-1].lower()
    if domain in PLACEHOLDER_DOMAINS:
        return False
    if domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return False
    return True


def find_internal_links(html: str, base_url: str, max_links: int = 6) -> List[str]:
    """Pick a small set of internal links worth crawling for contact info."""
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc
    candidates = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc and parsed.netloc != base_domain:
            continue  # external link, not useful for contact discovery
        text = (a.get_text() or "").lower()
        haystack = f"{href.lower()} {text}"
        if any(hint in haystack for hint in CONTACT_PAGE_HINTS):
            if full_url not in seen:
                seen.add(full_url)
                candidates.append(full_url)
        if len(candidates) >= max_links:
            break

    return candidates


def extract_contacts_from_html(html: str, page_url: str) -> ContactBundle:
    """Extract everything findable from a single page's HTML."""
    bundle = ContactBundle(pages_scanned=[page_url])
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)

    # 1. mailto: links (highest confidence — explicitly published by the business)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            email = href.split(":", 1)[1].split("?")[0].strip()
            if email and is_plausible_email(email):
                bundle.emails.append(EmailCandidate(
                    email=email, source_url=page_url, visible_on_page=True,
                    category=classify_email(email), needs_verification=False, confidence=0.95,
                ))

    # 2. Plain visible emails in text/HTML
    for match in EMAIL_RE.findall(html):
        if is_plausible_email(match) and not any(e.email.lower() == match.lower() for e in bundle.emails):
            bundle.emails.append(EmailCandidate(
                email=match, source_url=page_url, visible_on_page=True,
                category=classify_email(match), needs_verification=False, confidence=0.9,
            ))

    # 3. Obfuscated emails (lower confidence — reconstructed, should be verified)
    for local, domain, tld in OBFUSCATED_EMAIL_RE.findall(text):
        email = f"{local}@{domain}.{tld}"
        if is_plausible_email(email) and not any(e.email.lower() == email.lower() for e in bundle.emails):
            bundle.emails.append(EmailCandidate(
                email=email, source_url=page_url, visible_on_page=False,
                category=classify_email(email), needs_verification=True, confidence=0.55,
            ))

    # 4. JSON-LD schema.org contact info (organization/contactPoint)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            email = node.get("email")
            if email and is_plausible_email(email) and not any(e.email.lower() == email.lower() for e in bundle.emails):
                bundle.emails.append(EmailCandidate(
                    email=email, source_url=page_url, visible_on_page=True,
                    category=classify_email(email), needs_verification=False, confidence=0.9,
                ))
            phone = node.get("telephone")
            if phone and phone not in bundle.phones:
                bundle.phones.append(phone)

    # 5. Phone numbers in visible text (best-effort, noisy — keep top few unique)
    for match in PHONE_RE.findall(text):
        cleaned = match.strip()
        digit_count = sum(c.isdigit() for c in cleaned)
        if 7 <= digit_count <= 13 and cleaned not in bundle.phones:
            bundle.phones.append(cleaned)
    bundle.phones = bundle.phones[:3]

    # 6. Social links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        domain = urlparse(href).netloc.replace("www.", "")
        for social_domain, platform in SOCIAL_DOMAINS.items():
            if domain == social_domain and platform not in bundle.social_links:
                bundle.social_links[platform] = href

    # 7. Contact form heuristic: a <form> on a page whose URL/title suggests contact/enquiry
    if soup.find("form") and any(h in page_url.lower() for h in ("contact", "enquir", "inquir", "book")):
        bundle.contact_form_url = page_url

    return bundle


def merge_bundles(bundles: List[ContactBundle]) -> ContactBundle:
    merged = ContactBundle()
    seen_emails = set()
    for b in bundles:
        merged.pages_scanned.extend(b.pages_scanned)
        for e in b.emails:
            if e.email.lower() not in seen_emails:
                seen_emails.add(e.email.lower())
                merged.emails.append(e)
        for p in b.phones:
            if p not in merged.phones:
                merged.phones.append(p)
        merged.social_links.update(b.social_links)
        if not merged.contact_form_url and b.contact_form_url:
            merged.contact_form_url = b.contact_form_url
    return merged
