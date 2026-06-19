"""
Page speed via Google PageSpeed Insights API.

Best-effort and optional: if GOOGLE_PSI_API_KEY isn't set, or the call fails
or times out, the pipeline continues without it (per the brief: speed is
supporting evidence, not a core requirement). The free unauthenticated quota
is very low, so an API key is recommended — get one at
https://developers.google.com/speed/docs/insights/v5/get-started (free).
"""

import os
from dataclasses import dataclass
from typing import Optional

import httpx

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_TIMEOUT_S = 20


@dataclass
class SpeedResult:
    mobile_score: Optional[int] = None       # 0-100, Lighthouse performance score
    desktop_score: Optional[int] = None
    main_issue: Optional[str] = None
    error: Optional[str] = None

    def human_summary(self) -> str:
        if self.error:
            return f"Page speed check unavailable ({self.error})"
        parts = []
        if self.mobile_score is not None:
            parts.append(f"mobile performance {self.mobile_score}/100")
        if self.desktop_score is not None:
            parts.append(f"desktop performance {self.desktop_score}/100")
        if self.main_issue:
            parts.append(f"main issue: {self.main_issue}")
        return "; ".join(parts) if parts else "No page speed data"


def _run_psi(url: str, strategy: str, api_key: str) -> dict:
    params = {"url": url, "strategy": strategy, "category": "PERFORMANCE"}
    if api_key:
        params["key"] = api_key
    with httpx.Client(timeout=PSI_TIMEOUT_S) as client:
        resp = client.get(PSI_ENDPOINT, params=params)
        resp.raise_for_status()
        return resp.json()


def _extract_score_and_issue(payload: dict) -> tuple[Optional[int], Optional[str]]:
    try:
        lighthouse = payload["lighthouseResult"]
        score = round(lighthouse["categories"]["performance"]["score"] * 100)
    except (KeyError, TypeError):
        return None, None

    issue = None
    try:
        audits = lighthouse["audits"]
        # Pick the worst-scoring opportunity audit with a real title, as a plain-English main issue
        opportunities = [
            a for a in audits.values()
            if a.get("score") is not None and a["score"] < 0.5 and a.get("details", {}).get("type") == "opportunity"
        ]
        opportunities.sort(key=lambda a: a.get("score", 1))
        if opportunities:
            issue = opportunities[0].get("title")
    except (KeyError, TypeError):
        pass

    return score, issue


def check_page_speed(url: str) -> SpeedResult:
    api_key = os.environ.get("GOOGLE_PSI_API_KEY", "")
    try:
        mobile_payload = _run_psi(url, "mobile", api_key)
        mobile_score, issue = _extract_score_and_issue(mobile_payload)

        desktop_score = None
        try:
            desktop_payload = _run_psi(url, "desktop", api_key)
            desktop_score, _ = _extract_score_and_issue(desktop_payload)
        except Exception:
            pass  # desktop is nice-to-have; don't fail the whole check over it

        return SpeedResult(mobile_score=mobile_score, desktop_score=desktop_score, main_issue=issue)
    except Exception as exc:
        return SpeedResult(error=str(exc))
