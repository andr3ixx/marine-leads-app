"""
Per-lead pipeline. Orchestrates everything into the structured output row the
brief specifies. Designed to be called once per lead from either the CLI
script or the Streamlit app, with a Playwright `browser` and a Groq `client`
already constructed and passed in.
"""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from groq import Groq
from playwright.async_api import Browser

from . import scoring, speed as speed_mod, tech_stack
from .ai_analysis import analyse_lead
from .niches import NicheProfile, get_niche
from .scraper import scrape_lead
from .text_utils import extract_visible_text

OUTPUT_FIELDS = [
    "Company Name", "Website", "Niche Profile", "Lead Status",
    "Overall Score", "Visual Quality Score", "Inquiry Flow Score",
    "Mobile Usability Score", "Trust/Social Proof Score", "Local SEO Score",
    "Technical Score", "Commercial Opportunity Score",
    "Main Issue", "Best Outreach Angle", "Recommended Offer",
    "Email Found", "Email Category", "Email Confidence", "Email Needs Verification",
    "Email Source URL", "Phone Found", "Contact Form URL", "Social Links",
    "Detected Tech", "Page Speed Summary",
    "Desktop Screenshot Path", "Mobile Screenshot Path",
    "Email Draft", "Video Talking Points",
    "Verification Warnings", "Error",
]


def safe_filename(name: str, idx: int) -> str:
    safe = re.sub(r"[^\w\-]", "_", name)[:60]
    return safe.strip("_") or f"lead_{idx}"


async def run_lead(
    *,
    browser: Browser,
    groq_client: Groq,
    company: str,
    website: str,
    idx: int,
    niche_key: str,
    screenshot_dir: Path,
    check_speed: bool = False,
) -> dict:
    """Run the full pipeline for one lead. Never raises — failures land in
    the `Error` field and the row gets a 'Manual review' status."""

    niche: NicheProfile = get_niche(niche_key)
    row = {field: "" for field in OUTPUT_FIELDS}
    row["Company Name"] = company
    row["Website"] = website
    row["Niche Profile"] = niche.label

    if website and not re.match(r"https?://", website, re.IGNORECASE):
        website = "https://" + website

    safe_name = safe_filename(company, idx)
    desktop_shot = screenshot_dir / f"{safe_name}_desktop.png"
    mobile_shot = screenshot_dir / f"{safe_name}_mobile.png"

    try:
        scrape = await scrape_lead(browser, website, desktop_shot, mobile_shot)
        if not scrape.succeeded:
            row["Error"] = scrape.error or "Scrape failed"
            row["Lead Status"] = "Manual review"
            return row

        tech = tech_stack.detect_tech_stack(scrape.html)
        row["Detected Tech"] = ", ".join(tech) if tech else "None detected"
        text = extract_visible_text(scrape.html)

        speed_summary = None
        if check_speed:
            speed_result = speed_mod.check_page_speed(website)
            speed_summary = speed_result.human_summary()
            row["Page Speed Summary"] = speed_summary

        analysis = analyse_lead(
            groq_client, company, text, tech, niche,
            desktop_screenshot=scrape.desktop_screenshot,
            mobile_screenshot=scrape.mobile_screenshot,
            speed_summary=speed_summary,
        )

        sub_scores = scoring.SubScores(
            visual_design=analysis.visual_design_score,
            inquiry_flow=analysis.inquiry_flow_score,
            local_seo=analysis.local_seo_score,
            technical=analysis.technical_score,
            commercial=analysis.commercial_score,
            trust_social_proof=analysis.trust_social_proof_score,
        )
        overall = scoring.compute_overall_score(sub_scores, niche)

        best_email = scrape.contacts.best_email
        has_usable_contact = best_email is not None
        needs_verification = best_email.needs_verification if best_email else True

        status = scoring.determine_lead_status(
            overall_score=overall,
            has_usable_contact=has_usable_contact,
            contact_needs_verification=needs_verification,
            scrape_succeeded=True,
        )

        warnings = []
        if best_email and best_email.needs_verification:
            warnings.append("Email was reconstructed from obfuscated text — verify before sending.")
        if not best_email:
            warnings.append("No email found on site — manual lookup or Snov/Hunter needed.")
        if not scrape.mobile_screenshot:
            warnings.append("Mobile screenshot failed — visual mobile review based on desktop only.")

        row.update({
            "Lead Status": status,
            "Overall Score": overall,
            "Visual Quality Score": analysis.visual_design_score,
            "Inquiry Flow Score": analysis.inquiry_flow_score,
            "Mobile Usability Score": analysis.mobile_usability_score,
            "Trust/Social Proof Score": analysis.trust_social_proof_score,
            "Local SEO Score": analysis.local_seo_score,
            "Technical Score": analysis.technical_score,
            "Commercial Opportunity Score": analysis.commercial_score,
            "Main Issue": analysis.main_issue,
            "Best Outreach Angle": analysis.best_outreach_angle,
            "Recommended Offer": analysis.recommended_offer,
            "Email Found": best_email.email if best_email else "",
            "Email Category": best_email.category if best_email else "",
            "Email Confidence": round(best_email.confidence, 2) if best_email else "",
            "Email Needs Verification": needs_verification if best_email else "",
            "Email Source URL": best_email.source_url if best_email else "",
            "Phone Found": "; ".join(scrape.contacts.phones) if scrape.contacts.phones else "",
            "Contact Form URL": scrape.contacts.contact_form_url or "",
            "Social Links": json.dumps(scrape.contacts.social_links) if scrape.contacts.social_links else "",
            "Desktop Screenshot Path": str(desktop_shot) if scrape.desktop_screenshot else "",
            "Mobile Screenshot Path": str(mobile_shot) if scrape.mobile_screenshot else "",
            "Email Draft": analysis.email_draft,
            "Video Talking Points": json.dumps(analysis.video_talking_points),
            "Verification Warnings": "; ".join(warnings) if warnings else "",
        })
        return row

    except Exception as exc:
        row["Error"] = str(exc)
        row["Lead Status"] = "Manual review"
        return row
