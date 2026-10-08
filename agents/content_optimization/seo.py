"""Topic-grounded metadata normalization with an explicit optimized upload path."""
import re
from .quality import relevant


def normalize_tags(values, topic, limit=12):
    result, seen = [], set()
    for value in values:
        if not isinstance(value, str):
            continue
        tag = re.sub(r"#+", "", value).strip()
        if not tag or len(tag) > 60 or tag.casefold() in seen or not relevant(tag, topic):
            continue
        if sum(len(t) + 3 for t in result) + len(tag) + 3 > 450:
            break
        seen.add(tag.casefold())
        result.append(tag)
        if len(result) >= limit:
            break
    return result


def normalize_hashtags(values, shorts=False):
    result, seen = [], set()
    for value in (["Shorts"] if shorts else []) + list(values):
        if not isinstance(value, str):
            continue
        tag = re.sub(r"[^\w]", "", value)
        if not tag or tag.casefold() in seen or (not shorts and tag.casefold() == "shorts"):
            continue
        seen.add(tag.casefold())
        result.append("#" + tag)
        if len(result) == 3:
            break
    return result


def upload_description(script):
    # Only optimized scripts use this; legacy metadata is left untouched.
    description = re.sub(r"#+\w+", "", script.get("description", "")).strip()
    hashtags = normalize_hashtags(script.get("hashtags", []), script.get("video_type") == "shorts")
    footer = "\n\nSubscribe for more current-trend explainers!\n" + " ".join(hashtags)
    return description[:5000 - len(footer)] + footer


def diagnostics(script):
    title = script.get("title", "")
    opening = " ".join(script.get("description", "").splitlines()[:2])
    queries = script.get("search_queries", [])[:3]
    tags = script.get("tags", [])
    topic = script.get("topic", "")
    return {"description_valid": bool(opening) and relevant(opening, topic) and len(script.get("description", "")) <= 5000,
            "tags_valid": tags == normalize_tags(tags, topic),
            "title_topic_relevant": relevant(title, topic),
            "search_queries": queries,
            "query_coverage": [{"query": q, "title": relevant(title, q), "opening": relevant(opening, q)} for q in queries],
            "keywords": script.get("keywords", []), "hashtags": script.get("hashtags", [])}
