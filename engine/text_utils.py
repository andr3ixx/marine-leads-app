"""HTML -> readable text (unchanged logic from the v1 script)."""

import re
from bs4 import BeautifulSoup

MAX_TEXT_CHARS = 4000


def extract_visible_text(html: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "meta", "head", "svg", "img"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:max_chars]
