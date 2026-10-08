"""Conservative packaging checks; length limits are readability heuristics."""
import re
from .quality import relevant


def evaluate_title(text, topic):
    issues = []
    if not 1 <= len(text) <= 100 or "\n" in text:
        issues.append("invalid_length")
    if not relevant(text, topic):
        issues.append("off_topic")
    if len(text) > 60:
        issues.append("desktop_truncation_risk")
    if len(text) > 40:
        issues.append("mobile_truncation_risk")
    if len(re.findall(r"\b[A-Z]{3,}\b", text)) > 2:
        issues.append("excessive_caps")
    if re.search(r"won.t believe|shocking|mind.blowing|insane|secret revealed", text, re.I):
        issues.append("clickbait")
    return {"text": text, "characters": len(text), "issues": issues,
            "score": max(0, 100 - 15 * len(issues)),
            "valid": not any(x in issues for x in ("invalid_length", "off_topic", "excessive_caps", "clickbait"))}


def valid_thumbnail(text, title, evidence):
    words = text.split()
    # A short exact phrase from reviewed content adds no new claim.
    return (1 <= len(words) <= 3 and len(text) <= 32
            and text.casefold() in evidence.casefold()
            and text.casefold() not in title.casefold()
            and not re.search(r"[#<>\n]", text))
