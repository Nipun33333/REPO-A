import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import config
from agents import niche, topic_validation, us_trends


def _candidate(title="Inception ending explained", cid="x1", score=50, category=""):
    return {
        "video_id": cid,
        "title": title,
        "description": "A current US trending subject.",
        "channel": "Trend Channel",
        "category_id": category,
        "views": 1000,
        "trend_score": score,
        "published_at": "2026-09-28T08:00:00Z",
    }


def _mock_generate(monkeypatch, payload):
    monkeypatch.setattr(niche, "generate", lambda *args, **kwargs: json.dumps(payload))


@pytest.mark.parametrize("raw, expected", [
    ("Marvel!!!", "marvel"), ("US Trend-Topic", "us trend topic"),
    ("  Latest  News  ", "latest news"), ("A/B/C", "a b c"),
    ("Hello, WORLD", "hello world"), ("", ""), ("   ", ""),
    ("2026 Update", "2026 update"), ("GTA 6", "gta 6"),
    ("Minecraft LIVE", "minecraft live"), ("Foo...bar!!!baz", "foo bar baz"),
    ("A_B-C", "a b c"), ("Hidden Detail #1", "hidden detail 1"),
    ("What’s New?", "what s new"), ("A:B:C", "a b c"),
    ("Election 2026", "election 2026"), ("Tech AI chip", "tech ai chip"),
    ("NBA Finals", "nba finals"), ("Bitcoin update", "bitcoin update"),
])
def test_normalize_matrix(raw, expected):
    assert us_trends.normalize(raw) == expected


@pytest.mark.parametrize("text, expected", [
    ("normal trending video", False), ("graphic gore footage", True),
    ("sexual assault story", True), ("terrorism documentary", True),
    ("self harm discussion", True), ("mass shooting footage", True),
    ("child abuse documentary", True), ("music video", False),
    ("football match", False), ("science documentary", False),
    ("politics update", False), ("technology launch", False),
    ("rape allegation", True), ("dead body found", True),
    ("terrorist attack", True), ("graphic violence", True),
])
def test_safety_matrix(text, expected):
    assert us_trends.is_banned(text) is expected


@pytest.mark.parametrize("a,b,expected", [
    ("Minecraft update", "Minecraft update explained", True),
    ("NBA Finals", "NBA Finals recap", True),
    ("Inception ending", "Inception ending details", True),
    ("Bitcoin price", "Bitcoin price update", True),
    ("Movie trailer", "Movie trailer explained", True),
    ("random topic", "unrelated topic", False),
    ("Alpha Beta Core", "Alpha Beta Delta", True),
    ("A B C", "A D E", False),
    ("", "", False), ("", "topic", False), ("topic", "", False),
    ("NASA mission", "NASA mission timeline", True),
    ("Sports highlight", "finance update", False),
    ("Election debate", "election debate highlights", True),
    ("New phone launch", "new phone launch review", True),
    ("Game release", "game release trailer", True),
])
def test_similarity_matrix(a, b, expected):
    assert us_trends.topics_are_similar(a, b) is expected


@pytest.mark.parametrize("hours", [0.5, 1, 2, 4, 8, 12, 18, 24, 36, 48, 60, 72, 90, 120, 240])
def test_trend_score_is_finite(hours):
    published = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    score = us_trends.calculate_video_score({
        "views": 100_000, "likes": 5_000, "comments": 500, "published_at": published,
    })
    assert 0 <= score <= 100


@pytest.mark.parametrize("content_type", [
    "EXPLAINER", "BREAKDOWN", "ANALYSIS", "NEWS_EXPLAINER", "CONTEXT",
    "TIMELINE", "HOW_IT_WORKS", "RECAP", "TREND_EXPLAINER",
])
def test_semantic_content_types(monkeypatch, content_type):
    _mock_generate(monkeypatch, {
        "candidate_id": "x1", "content_type": content_type,
        "content_domain": "US_MOVIE", "content_angle": "Explain it",
        "why_it_fits": "Current trend", "confidence": 0.9,
    })
    selected = niche.select_semantic_candidate([_candidate()], config.CHANNEL_DESCRIPTION)
    assert selected["video_id"] == "x1"
    assert selected["content_domain"] == "US_MOVIE"
    assert selected["content_type"] == content_type


def test_selector_rejects_out_of_niche_domain(monkeypatch):
    _mock_generate(monkeypatch, {
        "candidate_id": "sports", "content_type": "RECAP",
        "content_domain": "SPORTS", "content_angle": "Why the game matters",
        "why_it_fits": "Strong current US trend", "confidence": 0.98,
    })
    candidates = [
        _candidate("Inception ending", "tech", 90, "28"),
        _candidate("NBA Finals controversy", "sports", 88, "17"),
        _candidate("Movie trailer", "movie", 87, "1"),
    ]
    with pytest.raises(RuntimeError, match="movie/anime niche"):
        niche.select_semantic_candidate(candidates, config.CHANNEL_DESCRIPTION)


def test_selector_unknown_candidate_rejected(monkeypatch):
    _mock_generate(monkeypatch, {
        "candidate_id": "missing", "content_type": "EXPLAINER",
        "content_domain": "US_MOVIE", "content_angle": "x", "why_it_fits": "x", "confidence": 1,
    })
    with pytest.raises(ValueError, match="unknown candidate_id"):
        niche.select_semantic_candidate([_candidate()], config.CHANNEL_DESCRIPTION)


def test_manual_movie_topic_is_niche_gated(monkeypatch):
    _mock_generate(monkeypatch, {"candidate_id": "manual", "content_domain": "US_MOVIE"})
    out = niche.validate_manual_topic("Inception ending explained")
    assert out["content_domain"] == "US_MOVIE"
    assert out["content_type"] == "EXPLAINER"


def test_selector_prompt_requires_movies_or_anime():
    prompt = niche.build_selection_prompt([_candidate()], config.CHANNEL_DESCRIPTION).lower()
    assert "mandatory niche" in prompt
    assert "exclude general news" in prompt
    assert "japanese_anime" in prompt and "us_anime" in prompt
    assert "hidden" in prompt
    assert "candidates:" in prompt


def test_config_identity_is_movie_anime():
    text = config.CHANNEL_DESCRIPTION.lower()
    assert "current" in text
    assert "trending" in text
    assert "current" in text and "trending" in text
    assert config.CONTENT_MODE == "MOVIE_ANIME_EXPLANATION"


def test_topic_validation_accepts_movie():
    research = {
        "topic": "Inception ending explained",
        "source_trend": "Inception ending",
        "video_title": "What the Inception Ending Means",
        "hook_question": "Why is this Inception ending trending now?",
        "content_domain": "US_MOVIE",
        "content_type": "EXPLAINER",
    }
    topic_validation.validate_research_topic_lock(research)


@pytest.mark.parametrize("bad_domain", ["ANIME", "MARVEL", "SPORTS", "SCIENCE", "", "POP_CULTURE"])
def test_topic_validation_rejects_unrelated_domain(bad_domain):
    research = {
        "topic": "Inception ending explained",
        "source_trend": "Inception ending",
        "video_title": "What the Inception Ending Means",
        "hook_question": "Why is this Inception ending trending now?",
        "content_domain": bad_domain,
        "content_type": "EXPLAINER",
    }
    with pytest.raises(ValueError):
        topic_validation.validate_research_topic_lock(research)


@pytest.mark.parametrize("bad_type", ["SPORTS", "MOTIVATION", "FACTS", "", "FRANCHISE_UPDATE"])
def test_topic_validation_rejects_unknown_types(bad_type):
    research = {
        "topic": "Inception ending explained",
        "source_trend": "Inception ending",
        "video_title": "What the Inception Ending Means",
        "hook_question": "Why is this Inception ending trending now?",
        "content_domain": "US_MOVIE",
        "content_type": bad_type,
    }
    with pytest.raises(ValueError):
        topic_validation.validate_research_topic_lock(research)


def test_fetch_source_parallel_result_shape(monkeypatch):
    def fake_request(endpoint, params, timeout=8.0):
        return {"items": [{
            "id": "video-1",
            "snippet": {"title": "Current AI chip trend", "description": "desc", "publishedAt": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"), "channelTitle": "channel", "categoryId": "28"},
            "statistics": {"viewCount": "1000", "likeCount": "50", "commentCount": "5"},
        }], "nextPageToken": None}
    monkeypatch.setattr(us_trends, "youtube_request", fake_request)
    name, rows = us_trends._fetch_source("US_mostPopular", {"chart": "mostPopular"})
    assert name == "US_mostPopular"
    assert rows[0]["video_id"] == "video-1"


def test_category_ids_default_is_broad():
    assert config.DISCOVERY_CATEGORY_IDS == ()


def test_end_to_end_movie_selection(monkeypatch):
    candidates = [
        _candidate("Inception ending explained", "tech", 98, "28"),
        _candidate("NBA Finals controversy", "sports", 96, "17"),
        _candidate("Movie trailer explained", "movie", 94, "1"),
    ]
    monkeypatch.setattr(us_trends, "fetch_youtube_candidates", lambda: candidates)
    monkeypatch.setattr(us_trends, "load_used_topics", lambda: [])
    monkeypatch.setattr(niche, "generate", lambda *a, **k: json.dumps({
        "candidate_id": "movie", "content_type": "EXPLAINER", "content_domain": "US_MOVIE",
        "content_angle": "What changed and why it matters", "why_it_fits": "Strong current trend", "confidence": 0.99,
    }))
    out = us_trends.get_best_us_trending_topic(config.CHANNEL_DESCRIPTION)
    assert out["candidate_id"] == "movie"
    assert out["content_domain"] == "US_MOVIE"


def test_no_fallback_to_other_subject_when_selector_returns_null(monkeypatch):
    monkeypatch.setattr(us_trends, "fetch_youtube_candidates", lambda: [_candidate("Inception ending", "x")])
    monkeypatch.setattr(us_trends, "load_used_topics", lambda: [])
    monkeypatch.setattr(niche, "generate", lambda *a, **k: json.dumps({"candidate_id": None}))
    with pytest.raises(RuntimeError, match="No usable current US trend"):
        us_trends.get_best_us_trending_topic(config.CHANNEL_DESCRIPTION)


def test_trend_gate_reaches_later_batches(monkeypatch):
    candidates = [_candidate(f"Trend topic {i}", f"bad-{i}", 100-i, "28") for i in range(60)]
    calls = []
    good = _candidate("US trend worth explaining", "good", 1, "17")
    candidates.insert(35, good)

    def fake_selector(batch, channel):
        calls.append([x["video_id"] for x in batch])
        for item in batch:
            if item["video_id"] == "good":
                return {**item, "content_type": "EXPLAINER", "content_domain": "US_MOVIE", "content_angle": "Explain it", "why_it_fits": "Current trend", "semantic_confidence": 1}
        raise RuntimeError("No usable current US trend candidate matched the explanation criteria.")

    monkeypatch.setattr(us_trends, "select_semantic_candidate", fake_selector)
    out = us_trends.choose_best_trend(candidates, config.CHANNEL_DESCRIPTION)
    assert out["candidate_id"] == "good"
    assert len(calls) >= 2


def test_trend_gate_respects_max_batches(monkeypatch):
    candidates = [_candidate(f"Trend {i}", f"x{i}", 100-i, "28") for i in range(100)]
    calls = []
    def fake_selector(batch, channel):
        calls.append(batch)
        raise RuntimeError("No usable current US trend candidate matched the explanation criteria.")
    monkeypatch.setattr(us_trends, "select_semantic_candidate", fake_selector)
    monkeypatch.setattr(config, "DISCOVERY_SEMANTIC_BATCH_SIZE", 10)
    monkeypatch.setattr(config, "DISCOVERY_SEMANTIC_MAX_BATCHES", 3)
    with pytest.raises(RuntimeError):
        us_trends.choose_best_trend(candidates, config.CHANNEL_DESCRIPTION)
    assert len(calls) == 3


def _short_script(research):
    subject = research["topic"]
    return {
        "title": "Why This Trend Matters Now",
        "description": f"A concise explanation of {subject}.",
        "tags": ["Trending", "Explained", "#Shorts"],
        "topic": research["topic"],
        "source_trend": research["source_trend"],
        "content_domain": "US_MOVIE",
        "content_type": "EXPLAINER",
        "video_type": "shorts",
        "sections": [
            {
                "id": 1, "section_type": "hook", "title": "Hook",
                "narration": f"Here is why {subject} is suddenly everywhere right now.",
                "video_query": subject + " breaking trend footage",
                "video_query_2": subject + " latest development footage",
                "video_query_3": subject + " recent event footage",
                "video_query_4": subject + " current coverage footage",
                "bullet_points": [], "caption_text": subject, "duration_seconds": 7,
            },
            {
                "id": 2, "section_type": "explanation", "title": "What it means",
                "narration": f"The key point is what {subject} actually means and why the latest change matters.",
                "video_query": subject + " explanation footage",
                "video_query_2": subject + " analysis footage",
                "video_query_3": subject + " context footage",
                "video_query_4": subject + " latest update footage",
                "bullet_points": [], "caption_text": "Why it matters", "duration_seconds": 24,
            },
            {
                "id": 3, "section_type": "cta", "title": "CTA",
                "narration": "Follow for more current trend explainers.",
                "video_query": subject + " ending footage",
                "video_query_2": subject + " latest footage",
                "video_query_3": subject + " event footage",
                "video_query_4": subject + " closing coverage footage",
                "bullet_points": [], "caption_text": "More explainers", "duration_seconds": 6,
            },
        ],
    }


@pytest.mark.parametrize("iteration", range(100))
def test_100x_subject_integrity_accepts_creative_title(iteration):
    subject = f"Inception ending detail {iteration}"
    research = {
        "source_trend": subject,
        "topic": f"Why the {subject} matters now",
        "video_title": f"What Everyone Needs to Know About This {iteration}",
        "hook_question": f"Why is this {iteration} trend exploding?",
        "content_domain": "US_MOVIE",
        "content_type": "EXPLAINER",
        "key_points": ["latest change", "why it matters", "current context"],
    }
    assert topic_validation.validate_research_topic_lock(research) is None


@pytest.mark.parametrize("iteration", range(100))
def test_100x_subject_integrity_rejects_changed_source(iteration):
    subject = f"Inception ending detail {iteration}"
    research = {
        "source_trend": f"Completely different sports event {iteration}",
        "topic": f"Sports event {iteration}",
        "video_title": "A different story",
        "hook_question": "Why is this different story trending?",
        "content_domain": "US_MOVIE",
        "content_type": "EXPLAINER",
    }
    with pytest.raises(ValueError, match="source_trend drifted"):
        # Use researcher-level lock for canonical source equality.
        from agents import researcher
        researcher._validate_topic_integrity(research, subject)


@pytest.mark.parametrize("iteration", range(100))
def test_100x_movie_discovery_selection(iteration, monkeypatch):
    candidate_id = f"iter-{iteration}"
    subject = f"Inception movie ending detail {iteration}"
    candidate = _candidate(subject, candidate_id, 90, "28")
    monkeypatch.setattr(niche, "generate", lambda *a, cid=candidate_id, **k: json.dumps({
        "candidate_id": cid, "content_type": "EXPLAINER", "content_domain": "US_MOVIE",
        "content_angle": "Explain the update", "why_it_fits": "Current US trend", "confidence": 0.99,
    }))
    selected = niche.select_semantic_candidate([candidate], config.CHANNEL_DESCRIPTION)
    assert selected["video_id"] == candidate_id
    assert selected["content_domain"] == "US_MOVIE"


@pytest.mark.parametrize("iteration", range(100))
def test_100x_script_lock_accepts_topic_specific_queries(iteration):
    research = {
        "topic": f"Inception movie ending detail {iteration}",
        "source_trend": f"Inception movie ending detail {iteration}",
        "video_title": f"What the technology update means {iteration}",
        "hook_question": "Why is this update trending now?",
        "content_domain": "US_MOVIE",
        "content_type": "EXPLAINER",
        "key_points": ["latest update", "why it matters", "current context"],
    }
    script = _short_script(research)
    topic_validation.validate_script_topic_lock(script, research)


def test_unsupported_domain_is_not_silently_accepted():
    research = {
        "topic": "Inception ending",
        "source_trend": "Inception ending",
        "video_title": "Inception ending explained",
        "hook_question": "Why is the Inception ending trending?",
        "content_domain": "MARVEL",
        "content_type": "EXPLAINER",
    }
    with pytest.raises(ValueError, match="Unsupported content domain"):
        topic_validation.validate_research_topic_lock(research)


def test_workflow_schedule_is_india_time():
    text = Path(".github/workflows/daily-short.yml").read_text(encoding="utf-8")
    for cron in ['cron: "0 1 * * *"', 'cron: "0 3 * * *"', 'cron: "0 6 * * *"']:
        assert cron in text
    assert text.count('timezone: "Asia/Kolkata"') == 3
    assert "VIDEO_PRIVACY: public" in text
    assert "PIPELINE_VIDEO_TYPE: shorts" in text


def test_discovery_sources_are_movie_anime_focused():
    specs = us_trends._source_specs()
    charts = [params for _, params in specs if "chart" in params]
    assert {params["regionCode"] for params in charts} == {"US", "JP"}
    assert all(params["videoCategoryId"] == "1" for params in charts)
    searches = [params for _, params in specs if "q" in params]
    assert len(searches) == 3
    assert all(params["type"] == "video" and params["publishedAfter"] for params in searches)


def test_readme_describes_movie_anime_niche():
    text = Path("README.md").read_text(encoding="utf-8").lower()
    assert "us/hollywood movies" in text and "japanese/us anime" in text
    assert "hidden details" in text


@pytest.mark.parametrize("domain,subject", [
    ("US_MOVIE", "Inception ending explained"),
    ("JAPANESE_ANIME", "One Piece episode hidden details"),
    ("US_ANIME", "Castlevania character explained"),
])
def test_allowed_domains_survive_selection_and_validation(monkeypatch, domain, subject):
    _mock_generate(monkeypatch, {"candidate_id": "x1", "content_domain": domain})
    selected = niche.select_semantic_candidate([_candidate(subject)])
    assert selected["content_domain"] == domain
    research = {"topic": subject, "source_trend": subject,
                "content_domain": domain, "content_type": "EXPLAINER"}
    topic_validation.validate_research_topic_lock(research)
    script = _short_script(research)
    script["content_domain"] = domain
    topic_validation.validate_script_topic_lock(script, research)


@pytest.mark.parametrize("domain", ["GENERAL_TREND", "SPORTS", "TECHNOLOGY", "", None])
def test_manual_topic_cannot_bypass_niche(monkeypatch, domain):
    _mock_generate(monkeypatch, {"candidate_id": "manual", "content_domain": domain})
    with pytest.raises(RuntimeError, match="movie/anime niche"):
        niche.validate_manual_topic("A technology launch")


def test_search_hydrates_statistics_and_paginates(monkeypatch):
    calls = []
    published = datetime.now(timezone.utc).isoformat()
    def request(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "search":
            page = params.get("pageToken")
            return {"items": [{"id": {"videoId": "v2" if page else "v1"}}],
                    "nextPageToken": None if page else "page2"}
        return {"items": [{"id": params["id"], "snippet": {
            "title": "Inception ending", "publishedAt": published, "categoryId": "1"},
            "statistics": {"viewCount": "12345", "likeCount": "300"}}]}
    monkeypatch.setattr(us_trends, "youtube_request", request)
    monkeypatch.setattr(config, "DISCOVERY_MAX_PAGES", 2)
    _, rows = us_trends._fetch_source("US_movies", {"q": "movie", "type": "video", "regionCode": "US"})
    assert [row["video_id"] for row in rows] == ["v1", "v2"]
    assert all(row["views"] == 12345 for row in rows)
    assert [endpoint for endpoint, _ in calls] == ["search", "videos", "search", "videos"]
    assert calls[2][1]["pageToken"] == "page2"
    assert calls[0][1]["part"] == "snippet"
    assert "q" not in calls[1][1] and "pageToken" not in calls[1][1]


def test_empty_search_does_not_request_unfiltered_videos(monkeypatch):
    calls = []
    def request(endpoint, params):
        calls.append(endpoint)
        return {"items": []}
    monkeypatch.setattr(us_trends, "youtube_request", request)
    assert us_trends._fetch_source("US_anime", {"q": "anime"})[1] == []
    assert calls == ["search"]


def test_japanese_titles_are_not_repeated(monkeypatch):
    title = "ホタルの嫁入り 第二話 予告"
    monkeypatch.setattr(us_trends, "load_used_topics", lambda: [title])
    assert us_trends.filter_candidates([_candidate(title)]) == []
    assert not us_trends.topics_are_similar(title, "ワンピース 最新話")


def test_japanese_source_can_support_anchored_english_research():
    from agents import researcher
    source = "ホタルの嫁入り 第二話 予告"
    context = {"content_angle": "Hotaru no Yomeiri episode two character explanation"}
    result = {"source_trend": source, "topic": "Hotaru no Yomeiri character explanation"}
    assert researcher._validate_topic_integrity(result, source, context) is result
    with pytest.raises(ValueError, match="topic drifted"):
        researcher._validate_topic_integrity(
            {"source_trend": source, "topic": "Bitcoin price forecast"}, source, context)


def test_research_retries_japanese_output_in_english(monkeypatch):
    from agents import researcher
    source = "ホタルの嫁入り 第二話 予告"
    trend = {"selected_trend": source, "content_domain": "JAPANESE_ANIME",
             "content_angle": "Hotaru no Yomeiri character explanation"}
    data = {"source_trend": source, "topic": source, "video_title": source,
            "content_domain": "JAPANESE_ANIME", "content_type": "EXPLAINER",
            "key_points": ["Hotaru no Yomeiri characters"], "tags": ["anime"]}
    answers = iter([data, {**data, "topic": "Hotaru no Yomeiri character explanation",
                          "video_title": "Hotaru no Yomeiri explained"}])
    calls = []
    def generate(prompt):
        calls.append(prompt)
        return json.dumps(next(answers))
    monkeypatch.setattr(researcher, "generate", generate)
    result = researcher._research_selected_candidate(trend, config.CHANNEL_DESCRIPTION, [])
    assert result["topic"] == "Hotaru no Yomeiri character explanation"
    assert result["source_trend"] == source
    assert len(calls) == 2 and "OUTPUT LANGUAGE: English" in calls[0]


def test_japanese_source_query_repair_uses_english_work():
    research = {"topic": "Hotaru no Yomeiri character explanation",
                "source_trend": "ホタルの嫁入り 第二話 予告",
                "content_domain": "JAPANESE_ANIME", "content_type": "EXPLAINER"}
    script = _short_script(research)
    script["content_domain"] = "JAPANESE_ANIME"
    script["sections"][0]["video_query"] = ""
    topic_validation.repair_script_video_queries(script, research)
    assert "Hotaru no Yomeiri" in script["sections"][0]["video_query"]
    topic_validation.validate_script_topic_lock(script, research)
    script["sections"][0]["narration"] = "ホタルの嫁入り 第二話"
    with pytest.raises(ValueError, match="English and romanized"):
        topic_validation.validate_script_topic_lock(script, research)
