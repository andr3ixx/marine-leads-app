"""
Niche profiles for the lead qualification engine.

Per the product brief: one core engine, multiple niche profiles. For now only
`fishing_charter` and `general_charter` are built out properly — they share
almost all logic but differ in scoring emphasis, the AI system prompt, and the
language used in outreach. New niches (marina, marine_services, boat_builder,
marine_ecommerce) can be added later by dropping a new NicheProfile into
NICHE_PROFILES; nothing else in the engine needs to change.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class ScoringWeights:
    """Weights must sum to 1.0. Used to combine 0-100 sub-scores into one
    overall lead score."""
    visual_design: float
    inquiry_flow: float
    local_seo: float
    technical: float
    commercial: float
    trust_social_proof: float

    def __post_init__(self):
        total = (
            self.visual_design + self.inquiry_flow + self.local_seo
            + self.technical + self.commercial + self.trust_social_proof
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Scoring weights must sum to 1.0, got {total}")


@dataclass(frozen=True)
class NicheProfile:
    key: str
    label: str
    weights: ScoringWeights
    # Inserted into the AI system prompt to steer what it looks for / how it writes.
    focus_description: str
    outreach_voice: str
    extra_review_questions: tuple  # niche-specific things to check on top of the core charter checklist


CORE_CHARTER_QUESTIONS = (
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
    "Does the site rely too heavily on Facebook or a third-party booking platform "
    "instead of presenting itself as a real business?",
    "Does the design feel old, homemade, or below the quality of the actual experience on offer?",
)

NICHE_PROFILES: Dict[str, NicheProfile] = {
    "fishing_charter": NicheProfile(
        key="fishing_charter",
        label="Fishing Charter",
        weights=ScoringWeights(
            visual_design=0.35,
            inquiry_flow=0.20,
            local_seo=0.15,
            technical=0.10,
            commercial=0.10,
            trust_social_proof=0.10,
        ),
        focus_description=(
            "This is a FISHING CHARTER business. Beyond the core charter checklist, weigh heavily: "
            "whether target species are shown clearly, whether catch photos are used well, whether "
            "different trip types (half-day, full-day, species-specific) are explained, whether the "
            "captain's experience/credentials are clear, and whether the site would build trust with "
            "both tourists and serious local anglers. Also consider local SEO relevance around "
            "'[location] + fishing charter' style terms."
        ),
        outreach_voice=(
            "Write like Peter, who works with fishing charter operators specifically. Lean on language "
            "like fishing trips, target species, local anglers and tourists, catch photos, captain "
            "credibility, and trip types. The email should reference ONE or TWO specific, concrete "
            "observations from the site — not a generic audit."
        ),
        extra_review_questions=(
            "Are target species shown clearly (e.g. species names/photos, not just 'fishing trips')?",
            "Are catch photos used well, or are they missing/low quality/stock-looking?",
            "Are different fishing trip types explained (half-day vs full-day vs species-specific)?",
            "Is the captain's experience and credibility clear?",
            "Would this site build trust with both casual tourists AND serious local anglers?",
            "Is there visible local SEO relevance (location + fishing charter terms) on the page?",
        ),
    ),
    "general_charter": NicheProfile(
        key="general_charter",
        label="General Charter / Boat Tours",
        weights=ScoringWeights(
            visual_design=0.35,
            inquiry_flow=0.20,
            local_seo=0.15,
            technical=0.10,
            commercial=0.10,
            trust_social_proof=0.10,
        ),
        focus_description=(
            "This is a GENERAL CHARTER / BOAT TOUR business (day trips, private boat hire, family trips, "
            "sightseeing, wildlife tours, sailing charters — not fishing-specific). Beyond the core "
            "charter checklist, weigh heavily: guest experience framing, clarity of trip/tour options, "
            "private hire availability, family/tourist appeal, and how easy it is to check availability "
            "or enquire."
        ),
        outreach_voice=(
            "Write like Peter, who works with boat tour and charter operators. Lean on language like day "
            "trips, private boat hire, family trips, coastal tours, sightseeing, guest experience, and "
            "availability — with little to no fishing-specific language. Reference ONE or TWO specific, "
            "concrete observations from the site."
        ),
        extra_review_questions=(
            "Are the different trip/tour options (sightseeing, private hire, sunset cruise, etc.) easy to tell apart?",
            "Does the site sell the GUEST EXPERIENCE (what it feels like) rather than just listing specs?",
            "Is private/group booking clearly available and easy to request?",
            "Does the site appeal to families and tourists specifically, not just enthusiasts?",
            "Is availability/booking information easy to find or check?",
        ),
    ),
}

DEFAULT_NICHE = "fishing_charter"


def get_niche(key: str) -> NicheProfile:
    profile = NICHE_PROFILES.get(key)
    if profile is None:
        raise KeyError(f"Unknown niche profile '{key}'. Known: {list(NICHE_PROFILES)}")
    return profile
