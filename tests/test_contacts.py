import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.contacts import extract_contacts_from_html, find_internal_links, merge_bundles

SAMPLE_HOME_HTML = """
<html><body>
<header><a href="/">Home</a><a href="/contact-us">Contact</a><a href="/our-team">Our Team</a>
<a href="https://facebook.com/example">FB</a></header>
<main>
  <p>Call us at (555) 123-4567 or email bookings@example-charters.com</p>
  <p>Reach the owner directly: sarah [at] example-charters [dot] com</p>
</main>
<script type="application/ld+json">
{"@type": "Organization", "email": "info@example-charters.com", "telephone": "555-987-6543"}
</script>
</body></html>
"""

SAMPLE_CONTACT_HTML = """
<html><body>
<form action="/submit"><input name="email"></form>
<a href="mailto:enquiries@example-charters.com">Email us</a>
</body></html>
"""


def test_extract_mailto_and_visible_and_obfuscated():
    bundle = extract_contacts_from_html(SAMPLE_HOME_HTML, "https://example-charters.com/")
    emails = {e.email.lower() for e in bundle.emails}
    assert "bookings@example-charters.com" in emails
    assert "info@example-charters.com" in emails
    assert "sarah@example-charters.com" in emails
    assert "555-987-6543" in bundle.phones or any("987" in p for p in bundle.phones)
    assert bundle.social_links.get("Facebook") == "https://facebook.com/example"
    print("OK: extraction")


def test_classification_and_confidence():
    bundle = extract_contacts_from_html(SAMPLE_HOME_HTML, "https://example-charters.com/")
    by_email = {e.email.lower(): e for e in bundle.emails}
    assert by_email["bookings@example-charters.com"].category == "bookings"
    assert by_email["info@example-charters.com"].category == "info"
    assert by_email["sarah@example-charters.com"].needs_verification is True
    assert by_email["bookings@example-charters.com"].needs_verification is False
    print("OK: classification")


def test_internal_link_discovery():
    links = find_internal_links(SAMPLE_HOME_HTML, "https://example-charters.com/")
    assert any("contact-us" in l for l in links)
    assert any("our-team" in l for l in links)
    assert all("facebook.com" not in l for l in links)  # external links excluded
    print("OK: internal links")


def test_merge_and_best_email():
    b1 = extract_contacts_from_html(SAMPLE_HOME_HTML, "https://example-charters.com/")
    b2 = extract_contacts_from_html(SAMPLE_CONTACT_HTML, "https://example-charters.com/contact-us")
    merged = merge_bundles([b1, b2])
    best = merged.best_email
    # bookings/enquiries (visible, high priority category) should outrank generic info or personal-guess
    assert best is not None
    assert best.category in ("bookings",)
    assert merged.contact_form_url == "https://example-charters.com/contact-us"
    print(f"OK: merge + best_email -> {best.email} ({best.category}, conf={best.confidence})")


if __name__ == "__main__":
    test_extract_mailto_and_visible_and_obfuscated()
    test_classification_and_confidence()
    test_internal_link_discovery()
    test_merge_and_best_email()
    print("\nAll contact-discovery tests passed.")
