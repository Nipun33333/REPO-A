"""Semantic selector for current US trending-topic explanations.

This module has no fixed niche gate. Candidates come from broad current US YouTube
signals and Gemini selects one current subject that can support an explanation,
breakdown, context, analysis, or recap video.
"""
from __future__ import annotations

import json
import re
from typing import Any

from agents.gemini_client import generate
import config


CONTENT_MODE = "US_TREND_EXPLANATION"
ALLOWED_CONTENT_TYPES = {
    "EXPLAINER",
    "BREAKDOWN",
    "ANALYSIS",
    "NEWS_EXPLAINER",
    "CONTEXT",
    "TIMELINE",
    "HOW_IT_WORKS",
    "RECAP",
    "TREND_EXPLAINER",
}


def _topic_text(value: Any) -> str:
    if isinstance(value, dict):
        value = " ".join(_topic_text(v) for v in value.values())
    elif isinstance(value, (list, tuple)):
        value = " ".join(_topic_text(v) for v in value)
    return re.sub(r"[^\w]+", " ", str(value or "").casefold()).strip()


def _has_phrase(text: str, phrases: str) -> bool:
    return any(f" {phrase} " in f" {text} " for phrase in phrases.split("|"))


def _country_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, (list, tuple)):
        return [country for item in value for country in _country_values(item)]
    return [_topic_text(item) for item in str(value or "").split(",")]


def topic_is_eligible(candidate: dict) -> bool:
    """Check source evidence, never a model's category or a feed's region.

    Unknown subjects fail closed. Channel country and translated audio alone
    do not establish production origin; inspect the supplied subject metadata.
    Mixed India/international roundups are skipped rather than rewritten.
    """
    title = _topic_text(candidate.get("title"))
    if not title:
        return False
    subject = _topic_text([candidate.get(k) for k in (
        "title", "description", "topic_validation_description", "tags", "origin", "country_of_origin",
        "origin_country", "production_country", "production_countries",
    )])
    country_values = _country_values([candidate.get(k) for k in (
        "origin_country", "country_of_origin", "production_country",
        "production_countries", "origin", "country",
    )])
    countries = _topic_text(country_values)
    if any(value in {"in", "ind"} for value in country_values) or _has_phrase(countries, "india|indian"):
        return False
    # ISO country codes are compared as complete field values: the word "in"
    # in "made in Japan" must not be mistaken for India's country code.
    country_codes = set((
        "ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by bz "
        "ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz de dj dk dm do dz ec ee eg eh er es et fi fj fk fm fo fr "
        "ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im io iq ir is it je jm jo jp "
        "ke kg kh ki km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw mx my mz "
        "na nc ne nf ng ni nl no np nr nu nz om pa pe pf pg ph pk pl pm pn pr ps pt pw py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz "
        "tc td tf tg th tj tk tl tm tn to tr tt tv tw tz ua ug um us uy uz va vc ve vg vi vn vu wf ws ye yt za zm zw"
    ).split())
    known_origin = any(value in country_codes for value in country_values) or _has_phrase(countries,
        "usa|united states|jpn|japan|uk|united kingdom|canada|australia|new zealand|"
        "france|germany|italy|spain|south korea|china|taiwan|brazil|mexico|south africa"
    )
    international_subject = _has_phrase(subject,
        "hollywood|japan|japanese|anime|british|united kingdom|canada|canadian|"
        "australia|australian|french|france|german|germany|korean|south korea|"
        "chinese|china|spanish|spain|italian|italy|brazil|brazilian|mexico|mexican|"
        "marvel|dc comics|dc studios|superman|batman|spider man|avengers|"
        "indiana jones|playstation|xbox|nintendo|minecraft|fortnite|gta|grand theft auto|"
        "nasa|artemis|spacex|nba|nfl|nhl|mlb|taylor swift|beyonce|billie eilish|"
        "ariana grande|lady gaga|tom cruise|tom hanks|leonardo dicaprio|"
        "robert downey jr|zendaya|openai|chatgpt|nvidia|microsoft|apple|google|"
        "sony|steam|valve|capcom|square enix|elden ring|roblox"
    )
    # A translated international production is not an Indian production.
    translated = (known_origin or international_subject) and _has_phrase(subject, "dub|dubbed|subtitles")
    if translated:
        subject = re.sub(r"\b(?:hindi|telugu|tamil|malayalam|kannada|marathi|gujarati|punjabi)\s+(?:dub|dubbed|subtitles)\b", " ", subject)
    # Generated angles cannot introduce an India-centric subject either. They
    # are negative evidence only, never evidence of eligible source origin.
    focus = _topic_text([subject, candidate.get("content_angle"), candidate.get("why_it_fits")])
    # These geographic expressions are not references to the country India.
    focus = re.sub(r"\b(?:native american|american indian|indian ocean|west indies|west indian)\b", " ", focus)
    focus = re.sub(r"\s+", " ", focus).strip()
    if _has_phrase(focus,
        "india|indian|bharat|bollywood|tollywood|kollywood|mollywood|sandalwood|"
        "telugu|tamil|malayalam|kannada|hindi|marathi|gujarati|punjabi|bhojpuri|"
        "bengali cinema|odia|assamese|mumbai|delhi|chennai|hyderabad|bengaluru|"
        "bangalore|kolkata|kerala|tamil nadu|andhra pradesh|telangana|maharashtra|"
        "uttar pradesh|karnataka|gujarat|rajasthan|bihar|punjab|"
        "ipl|indian premier league|bcci|team india|chennai super kings|"
        "mumbai indians|royal challengers|virat kohli|rohit sharma|ms dhoni|"
        "sachin tendulkar|jasprit bumrah|narendra modi|rahul gandhi|amit shah|"
        "lok sabha|rajya sabha|bjp|isro|chandrayaan|"
        "shah rukh khan|shahrukh khan|salman khan|aamir khan|akshay kumar|"
        "deepika padukone|alia bhatt|priyanka chopra|ranbir kapoor|ranveer singh|"
        "rajinikanth|kamal haasan|thalapathy vijay|ajith kumar|allu arjun|"
        "prabhas|ram charan|jr ntr|mahesh babu|vijay devarakonda|vijay deverakonda|"
        "rashmika mandanna|samantha ruth prabhu|dhanush|mohanlal|mammootty|"
        "arijit singh|diljit dosanjh|anirudh ravichander|a r rahman|"
        "carryminati|total gaming|techno gamerz|triggered insaan|mortal gaming|"
        "scoutop|technical guruji|bb ki vines|ashish chanchlani|"
        "bigg boss|the kapil sharma show|panchayat|mirzapur|"
        "ranabaali|jailer 2|bhogi|aathi iva yarraa"):
        return False

    channel = _topic_text(candidate.get("channel"))
    if _has_phrase(channel,
        "t series|zee music|zee studios|sony music india|sun pictures|sun tv|"
        "saregama|aditya music|lahari music|think music india|tips official|"
        "yrf|yash raj films|dharma productions|mythri movie makers|"
        "hombale films|lyca productions|sri venkateswara creations|"
        "jiohotstar|jiocinema|aaj tak|republic bharat|ndtv india|star sports india"):
        return False

    languages = [str(candidate.get(k) or "").lower().split("-")[0] for k in (
        "default_language", "default_audio_language", "defaultLanguage", "defaultAudioLanguage",
    )]
    if not translated and any(code in {"hi", "te", "ta", "ml", "kn", "mr", "gu", "pa", "or", "as"} for code in languages):
        return False

    # Positive evidence must already be in the source. English language,
    # popularity in the US, or Gemini saying US_MOVIE are not origin evidence.
    production = _has_phrase(subject, "film|movie|cinema|trailer|teaser|song|music video|web series|ott")
    us_focus = _has_phrase(subject, "united states|us|usa|american")
    # A trailer trending in the US still needs production evidence.
    us_production = _has_phrase(subject, "american film|american movie|us production|us film|united states production")
    return known_origin or international_subject or us_production or (us_focus and not production) or channel in {
        "marvel entertainment", "dc", "warner bros pictures", "universal pictures",
        "paramount pictures", "walt disney studios", "20th century studios",
        "crunchyroll", "aniplex", "toho animation", "netflix anime",
        "playstation", "xbox", "nintendo of america",
    } or "ja" in languages


def clean_json_response(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.I).strip()
    raw = re.sub(r"```$", "", raw).strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError("Gemini returned no valid JSON object.")
    return json.loads(match.group())


def build_selection_prompt(candidates: list[dict], channel_description: str = "") -> str:
    rows = []
    for item in candidates:
        rows.append(json.dumps({
            "candidate_id": item.get("video_id"),
            "title": item.get("title", ""),
            "description": item.get("description", "")[:300],
            "channel": item.get("channel", ""),
            "tags": item.get("tags", []),
            "origin": {k: item[k] for k in ("origin", "origin_country", "country_of_origin", "production_country", "production_countries", "country") if item.get(k)},
            "default_language": item.get("default_language", ""),
            "default_audio_language": item.get("default_audio_language", ""),
            "category_id": item.get("category_id", ""),
            "views": item.get("views", 0),
            "likes": item.get("likes", 0),
            "comments": item.get("comments", 0),
            "trend_score": item.get("trend_score", 0),
            "published_at": item.get("published_at", ""),
        }, ensure_ascii=False))

    return f"""You are the current-US-trend selector for a YouTube explanation channel.

CHANNEL POSITIONING:
{channel_description}

GOAL:
Select ONE genuinely current, high-signal US trending candidate from the list.
The selected candidate becomes the immutable subject for the entire pipeline.
Select engaging trending topics for a United States audience. Exclude India-centric
news, Indian cinema, Indian celebrities, regional Indian entertainment, Indian
sports, and other India-specific trends. Preserve relevant US and international
content, including Japanese anime.
Within that geographic rule, do not impose a fixed subject or franchise restriction.
Do not use a predefined category allowlist.

SELECTION RULES:
- Choose only a candidate_id present in the supplied list.
- Prefer strong current trend signals: recency, view velocity, engagement, and
  broad US interest.
- Prefer candidates that can be explained, contextualized, analyzed, or broken
  down in a short video.
- A raw clip/performance is acceptable when the surrounding subject itself is
  explainable; do not invent a different topic.
- Category metadata may be used only as supporting context; never prioritize or reject a candidate because of its category.
- Never invent a candidate, entity, or event.
- Check title, description, production origin, language, tags and channel together.
  US trend-feed placement, English titles, and a US_MOVIE label do not establish
  US origin. Exclude Indian films, songs, OTT releases, cricket/IPL, celebrities,
  politics, regional news, India-only launches and Indian gaming creators.
  Reject mixed roundups containing India-centric stories. If origin or primary
  focus is uncertain, require reliable supplied metadata; never invent evidence.
- If all candidates are unsafe or unusable, return candidate_id as null.

CANDIDATES:
""" + "\n".join(rows) + """

Return ONLY JSON:
{
  "candidate_id": "existing candidate_id or null",
  "content_type": "EXPLAINER | BREAKDOWN | ANALYSIS | NEWS_EXPLAINER | CONTEXT | TIMELINE | HOW_IT_WORKS | RECAP | TREND_EXPLAINER",
  "content_domain": "GENERAL_TREND",
  "content_angle": "specific explanation angle tied directly to the selected candidate",
  "why_it_fits": "brief reason this subject is worth explaining now",
  "confidence": 0.0
}
"""


def select_semantic_candidate(candidates: list[dict], channel_description: str = "") -> dict[str, Any]:
    if not candidates:
        raise ValueError("No candidates supplied to trend selector.")

    candidates = [item for item in candidates if topic_is_eligible(item)]
    while candidates:
        selected = _select_semantic_candidate(candidates, channel_description)
        if topic_is_eligible(selected):
            return selected
        # Rejected angles must not contaminate an otherwise eligible source.
        # Remove the source before retrying; no candidate can be retried forever.
        candidates = [item for item in candidates if str(item.get("video_id")) != str(selected.get("video_id"))]
    raise RuntimeError("No usable current US trend candidate passed topic validation.")


def _select_semantic_candidate(candidates: list[dict], channel_description: str) -> dict[str, Any]:
    prompt = build_selection_prompt(candidates, channel_description)
    try:
        raw = generate(
            prompt,
            timeout_seconds=getattr(config, "GEMINI_SELECTION_TIMEOUT_SECONDS", 30),
            max_models=getattr(config, "GEMINI_SELECTION_MAX_MODELS", 6),
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        raw = generate(prompt)

    result = clean_json_response(raw)
    candidate_id = result.get("candidate_id")
    if not candidate_id:
        raise RuntimeError("No usable current US trend candidate matched the explanation criteria.")

    lookup = {str(x.get("video_id")): x for x in candidates}
    selected = lookup.get(str(candidate_id))
    if selected is None:
        raise ValueError("Trend selector returned an unknown candidate_id.")
    if not topic_is_eligible(selected):
        raise RuntimeError("No usable current US trend candidate passed topic validation.")

    content_type = str(result.get("content_type", "EXPLAINER")).upper().strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        content_type = "EXPLAINER"

    selected = dict(selected)
    selected.update({
        "content_type": content_type,
        "content_domain": "GENERAL_TREND",
        "content_angle": str(result.get("content_angle", "")).strip(),
        "why_it_fits": str(result.get("why_it_fits", "")).strip(),
        "semantic_confidence": float(result.get("confidence", 0) or 0),
    })
    return selected


def validate_manual_topic(topic: str) -> dict[str, Any]:
    """Apply the same geographic validation to a user-supplied topic."""
    topic = topic.strip()
    if not topic:
        raise ValueError("Manual topic cannot be empty.")
    if not topic_is_eligible({"title": topic}):
        raise ValueError("Manual topic is India-related or lacks reliable eligibility evidence.")
    return {
        "video_id": "manual",
        "title": topic,
        "description": "User-supplied topic.",
        "channel": "manual",
        "category_id": "",
        "views": 0,
        "trend_score": 0,
        "published_at": "",
        "content_type": "EXPLAINER",
        "content_domain": "GENERAL_TREND",
        "content_angle": "Explain the selected topic clearly and directly.",
        "semantic_confidence": 1.0,
    }
