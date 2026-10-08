"""Validation and sanitized, atomic diagnostic reports."""
import json
import os
import re
from pathlib import Path

from agents.topic_validation import topic_terms, validate_script_topic_lock


def sentences(text):
    # Avoid severing common English names/acronyms in a spoken opening.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    result, pending = [], ""
    for part in parts:
        pending = (pending + " " + part).strip()
        if re.search(r"\b(?:Mr|Mrs|Ms|Dr|Prof|St|U\.S|U\.K)\.$|\b[A-Z]\.$", pending):
            continue
        if pending:
            result.append(pending)
        pending = ""
    if pending:
        result.append(pending)
    return result


def word_count(script):
    return sum(len(s["narration"].split()) for s in script["sections"])


def relevant(text, topic):
    anchors = topic_terms(topic)
    return bool(anchors) and len(topic_terms(text) & anchors) >= min(2, len(anchors))


def supported(candidate, evidence, topic):
    """Preflight only; semantic support requires a separate model review."""
    if not isinstance(candidate, str) or not candidate.strip() or len(candidate) > 4000:
        return False
    numbers = set(re.findall(r"\b\d[\d,.]*%?", candidate))
    return (relevant(candidate, topic)
            and numbers <= set(re.findall(r"\b\d[\d,.]*%?", evidence))
            and not re.search(r"https?://|<|>", candidate))


def validate_change(script, original, research):
    for key in ("topic", "source_trend", "video_type", "content_domain", "content_type"):
        if script.get(key) != original.get(key):
            raise ValueError("canonical_identity_changed")
    validate_script_topic_lock(script, research)
    for old, new in zip(original["sections"], script["sections"]):
        for key in old.keys() | new.keys():
            if key != "narration" and old.get(key) != new.get(key):
                raise ValueError("section_contract_changed")
    if any(a["narration"] != b["narration"] for a, b in zip(script["sections"], original["sections"])):
        low, high = (70, 85) if script["video_type"] == "shorts" else (920, 1100)
        if not low <= word_count(script) <= high:
            raise ValueError("word_budget")


def sanitize(value):
    """Never serialize arbitrary exception objects, config, or research mappings."""
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()
                if not re.search(r"token|secret|password|cookie|api_key|credential", k, re.I)}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        for key, secret in os.environ.items():
            if re.search(r"TOKEN|SECRET|PASSWORD|COOKIE|API_KEY|CREDENTIAL", key, re.I) and len(secret) >= 4:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"AIza[\w-]+|ya29\.[\w.-]+|1//[\w-]+", "[REDACTED]", value)
        value = re.sub(r"(?i)(bearer\s+|(?:api_key|token|secret|cookie|password)\s*[=:]\s*)\S+", r"\1[REDACTED]", value)
    return value


def write_report(report, output_dir):
    path = Path(output_dir) / "content_quality_report.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(sanitize(report), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(path)
        print("   Content optimization: quality report saved.")
    except Exception:
        print("   Content optimization: report unavailable; continuing with validated content.")
