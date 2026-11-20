"""Offline regression tests for the opt-in viral-potential discovery strategy."""
from agents import us_trends
import config


def _candidate(video_id, published_at, views, likes, comments):
    return {
        "video_id": video_id,
        "title": "Movie or anime source " + video_id,
        "published_at": published_at,
        "views": views,
        "likes": likes,
        "comments": comments,
    }


def test_viral_mode_prefers_recent_engaged_breakout(monkeypatch):
    monkeypatch.setattr(config, "DISCOVERY_MODE", "viral")
    monkeypatch.setattr(us_trends, "_age_hours", lambda t: {"fresh": 2.0, "old": 60.0}[t])
    fresh = _candidate("fresh", "fresh", 30_000, 3_000, 300)
    old = _candidate("old", "old", 600_000, 2_000, 100)

    assert us_trends.calculate_viral_score(fresh) > us_trends.calculate_viral_score(old)
    ranked = us_trends._dedupe_and_score([old, fresh])
    assert [item["video_id"] for item in ranked] == ["fresh", "old"]
    assert all(0 <= item["viral_score"] <= 100 for item in ranked)
    assert all(item["views_per_hour"] >= 0 for item in ranked)


def test_switching_back_to_trending_keeps_legacy_score(monkeypatch):
    monkeypatch.setattr(config, "DISCOVERY_MODE", "trending")
    monkeypatch.setattr(us_trends, "_age_hours", lambda _: 12.0)
    videos = [
        _candidate("a", "same", 1_000, 50, 5),
        _candidate("b", "same", 100_000, 500, 30),
    ]
    ranked = us_trends._dedupe_and_score(videos)
    assert [v["trend_score"] for v in ranked] == sorted(
        [v["trend_score"] for v in ranked], reverse=True
    )


def test_viral_mode_includes_fresh_search_sources(monkeypatch):
    monkeypatch.setattr(config, "DISCOVERY_MODE", "viral")
    viral = us_trends._source_specs()
    assert any(params.get("order") == "date" for _, params in viral)
    monkeypatch.setattr(config, "DISCOVERY_MODE", "trending")
    trending = us_trends._source_specs()
    assert not any(params.get("order") == "date" for _, params in trending)


def test_selection_ranks_full_pool_before_candidate_limit(monkeypatch):
    monkeypatch.setattr(config, "DISCOVERY_MODE", "viral")
    monkeypatch.setattr(config, "DISCOVERY_CANDIDATE_LIMIT", 1)
    monkeypatch.setattr(us_trends, "topic_is_eligible", lambda _: True)

    def choose_first(batch, channel_description):
        return {
            **batch[0], "content_type": "EXPLAINER", "content_domain": "US_MOVIE",
            "content_angle": "Supported context",
        }

    monkeypatch.setattr(us_trends, "select_semantic_candidate", choose_first)
    first = {"video_id": "low", "title": "Low", "viral_score": 10}
    second = {"video_id": "high", "title": "High", "viral_score": 90}
    result = us_trends.choose_best_trend([first, second])
    assert result["candidate_id"] == "high"
    assert result["discovery_mode"] == "viral"
