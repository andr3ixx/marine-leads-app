"""
Lead scoring + status logic.

Sub-scores (0-100, higher = bigger opportunity / weaker current site) come
from the AI analysis step. This module just does the weighted combination and
turns that, plus contact-confidence, into the four-way status the brief asks
for: Pursue / Maybe / Skip / Manual review.
"""

from dataclasses import dataclass
from typing import Optional

from .niches import NicheProfile


@dataclass
class SubScores:
    visual_design: int          # weakness score: higher = weaker site = bigger opportunity
    inquiry_flow: int
    local_seo: int
    technical: int
    commercial: int
    trust_social_proof: int

    def clamp(self):
        for field_name in self.__dataclass_fields__:
            val = getattr(self, field_name)
            setattr(self, field_name, max(0, min(100, int(val))))
        return self


def compute_overall_score(scores: SubScores, niche: NicheProfile) -> int:
    scores.clamp()
    w = niche.weights
    total = (
        scores.visual_design * w.visual_design
        + scores.inquiry_flow * w.inquiry_flow
        + scores.local_seo * w.local_seo
        + scores.technical * w.technical
        + scores.commercial * w.commercial
        + scores.trust_social_proof * w.trust_social_proof
    )
    return round(total)


# Thresholds tuned around: "filter 200 leads down to 20-40 genuinely good
# opportunities" (see brief's success test). These are starting points —
# expected to be tuned after running a real test batch.
PURSUE_THRESHOLD = 65
MAYBE_THRESHOLD = 45


def determine_lead_status(
    overall_score: int,
    has_usable_contact: bool,
    contact_needs_verification: bool,
    scrape_succeeded: bool,
) -> str:
    """
    Pursue: clear weakness AND usable (not-uncertain) contact found.
    Manual review: potentially good lead but missing/uncertain info (or scrape failed).
    Maybe: some issues, but borderline / needs a human look either way.
    Skip: site already looks strong, or opportunity looks weak.
    """
    if not scrape_succeeded:
        return "Manual review"

    if overall_score >= PURSUE_THRESHOLD:
        if has_usable_contact and not contact_needs_verification:
            return "Pursue"
        return "Manual review"  # good opportunity, but contact info is missing/uncertain

    if overall_score >= MAYBE_THRESHOLD:
        return "Maybe"

    return "Skip"
