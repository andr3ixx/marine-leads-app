"""
AI analysis — text + visual review in one call.

Uses Groq's vision-capable model (llama-4-scout-17b-16e-instruct as of mid-2026;
check console.groq.com/docs/models if this changes) so a single call can reason
about both the page copy AND the screenshots, per the brief's "visual review is
the biggest missing piece" priority.

Sends up to 2 screenshots (desktop + mobile) as base64 data URIs alongside the
extracted text and detected tech stack, and asks for the full structured
output the brief specifies: weakness sub-scores, a specific (not generic)
main issue, recommended offer/outreach angle, an email draft, and Loom talking
points.
"""

import base64
import json
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from .niches import NicheProfile

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


class LeadAnalysis(BaseModel):
    # Weakness sub-scores, 0-100, higher = bigger website-rebuild opportunity
    visual_design_score: int = Field(ge=0, le=100)
    inquiry_flow_score: int = Field(ge=0, le=100)
    mobile_usability_score: int = Field(ge=0, le=100)  # reported separately; folded into inquiry_flow for weighting
    local_seo_score: int = Field(ge=0, le=100)
    technical_score: int = Field(ge=0, le=100)
    commercial_score: int = Field(ge=0, le=100)
    trust_social_proof_score: int = Field(ge=0, le=100)

    main_issue: str                          # specific, not "bad design"
    best_outreach_angle: str                 # the one thing to lead with
    recommended_offer: str                   # e.g. "Full rebuild", "Mobile/CRO refresh", "Light refresh"
    email_draft: str                         # plain text, <150 words, signed "— Peter"
    video_talking_points: List[str] = Field(min_length=3, max_length=3)


def _image_to_data_uri(path: Path) -> Optional[str]:
    if not path or not path.exists():
        return None
    ext = path.suffix.lstrip(".").lower() or "png"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_system_prompt(niche: NicheProfile) -> str:
    core_questions = "\n".join(f"- {q}" for q in (
        "Is it immediately obvious what the company offers within 5 seconds?",
        "Is the location clear?",
        "Are the trips or packages easy to understand?",
        "Is there a clear, obvious call to action?",
        "Is it easy to enquire from a mobile phone specifically?",
        "Is the site visually credible, or does it undersell the actual experience?",
        "Are there strong, well-used photos?",
        "Are reviews or testimonials visible?",
        "Is the captain/crew/company story clear and does it build trust?",
        "Are prices, trip lengths, or what's included easy to find?",
        "Is the contact form simple, or is it a barrier?",
        "Is the phone number or enquiry button obvious without scrolling?",
        "Does the site rely too heavily on Facebook or a third-party booking platform?",
        "Does the design feel old, homemade, or below the quality of the actual experience?",
    ))
    extra_questions = "\n".join(f"- {q}" for q in niche.extra_review_questions)

    return f"""\
You are Peter, an expert sales assistant at a digital marketing agency that helps marine
businesses grow their bookings online. {niche.focus_description}

You are given website COPY and SCREENSHOTS (desktop and/or mobile) of a real business's website.
The central question for every review: would a visitor trust this company enough to enquire
from their phone within 60 seconds?

Core checklist to consider:
{core_questions}

Niche-specific checklist:
{extra_questions}

Scoring philosophy: visual/design quality is usually a BIGGER opportunity signal than technical
issues. A site can be slow but if it LOOKS good, the owner won't feel urgency to replace it. If it
looks dated, confusing, cheap, or visually weak — even if technically fine — that's a strong
rebuild opportunity. Score each dimension 0-100 where HIGHER = WEAKER site = BIGGER opportunity for us
(NOT a quality score — a weakness/opportunity score).

{niche.outreach_voice}

Be specific. Do NOT write "the design is bad" or "needs improvement" — say what's actually wrong,
referencing something concrete from the copy or screenshot (e.g. "the homepage leads with a wall of
text and no photo of the boat" or "the mobile screenshot shows the phone number cut off below the fold").

You MUST respond with a single valid JSON object and nothing else, matching exactly this schema:
{{
  "visual_design_score": int 0-100,
  "inquiry_flow_score": int 0-100,
  "mobile_usability_score": int 0-100 (specifically how it performs/looks on the mobile screenshot),
  "local_seo_score": int 0-100,
  "technical_score": int 0-100,
  "commercial_score": int 0-100,
  "trust_social_proof_score": int 0-100,
  "main_issue": "specific string",
  "best_outreach_angle": "specific string, the single strongest thing to lead with",
  "recommended_offer": "short string, e.g. 'Full rebuild' / 'Mobile + CRO refresh' / 'Light visual refresh'",
  "email_draft": "plain text email under 150 words, opens with a specific observation, signed '— Peter'",
  "video_talking_points": ["point 1", "point 2", "point 3"]
}}
Do not include any text outside the JSON object."""


def build_user_content(
    company: str,
    text: str,
    tech_stack: List[str],
    desktop_screenshot: Optional[Path],
    mobile_screenshot: Optional[Path],
    speed_summary: Optional[str],
) -> list:
    tech_str = ", ".join(tech_stack) if tech_stack else "None detected"
    speed_str = speed_summary or "Not available"

    content: list = [{
        "type": "text",
        "text": (
            f"Company: {company}\n"
            f"Detected Tech Stack: {tech_str}\n"
            f"Page-speed notes: {speed_str}\n\n"
            f"Website text excerpt:\n\"\"\"\n{text}\n\"\"\""
        ),
    }]

    for label, shot in (("Desktop screenshot", desktop_screenshot), ("Mobile screenshot", mobile_screenshot)):
        data_uri = _image_to_data_uri(shot) if shot else None
        if data_uri:
            content.append({"type": "text", "text": f"{label}:"})
            content.append({"type": "image_url", "image_url": {"url": data_uri}})

    return content


def analyse_lead(
    client,
    company: str,
    text: str,
    tech_stack: List[str],
    niche: NicheProfile,
    desktop_screenshot: Optional[Path] = None,
    mobile_screenshot: Optional[Path] = None,
    speed_summary: Optional[str] = None,
) -> LeadAnalysis:
    system_message = build_system_prompt(niche)
    user_content = build_user_content(
        company, text, tech_stack, desktop_screenshot, mobile_screenshot, speed_summary
    )

    completion = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )

    raw = completion.choices[0].message.content
    if not raw:
        raise ValueError("Groq returned an empty response")
    return LeadAnalysis.model_validate_json(raw)
