"""Heuristic hook ranking, inspired by youtube-agent-skill's weakest-link model.

No bonus for adding numbers or sensational stakes. Scores do not predict views.
See THIRD_PARTY_NOTICES.md for attribution.
"""
import re
from .quality import relevant


def score_hook(text, topic):
    words = text.split()
    vague = len(re.findall(r"\b(amazing|insane|unbelievable|secret|shocking)\b", text, re.I))
    parts = {
        "specificity": max(0, (90 if relevant(text, topic) else 10) - 20 * vague),
        "curiosity": min(100, 35 + 20 * len(re.findall(r"\b(why|how|what|but|reason)\b", text, re.I)) + 15 * text.endswith("?")),
        "brevity": max(0, 100 - max(0, len(words) - 24, 9 - len(words)) * 7),
        "relevance": 100 if relevant(text, topic) else 0,
        "engagement": max(0, 65 + 20 * bool(re.search(r"\b(you|your|why|how|what)\b", text, re.I)) - 20 * vague),
    }
    return {"text": text, "properties": parts,
            "score": round(.6 * sum(parts.values()) / len(parts) + .4 * min(parts.values()))}
