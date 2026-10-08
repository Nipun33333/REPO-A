"""Exercise actual CLI orchestration and uploader with all network/media calls mocked."""
import importlib.util
import json
import sys
import types
from unittest.mock import Mock

import pytest
from PIL import Image

from tests.test_content_optimization import research, script, proposals, generator
from agents.content_optimization import optimizer
from uploader import youtube


@pytest.mark.parametrize("enabled", [True, False])
def test_pipeline_offline_integration(monkeypatch, tmp_path, research, script, proposals, enabled):
    for name, function in (("video.narrator", "generate_narration"), ("video.stock", "download_videos"), ("video.creator", "create_video")):
        module = types.ModuleType(name)
        setattr(module, function, Mock())
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("offline_pipeline", "pipeline.py")
    pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline)
    output = tmp_path / "output"
    output.mkdir()
    (output / "stale.txt").write_text("old")
    history = tmp_path / "used_topics.txt"
    history.write_text("persistent history")
    monkeypatch.setattr(pipeline.config, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(pipeline.config, "YT_OPTIMIZATION_ENABLED", enabled)
    monkeypatch.setenv("SKIP_YOUTUBE_UPLOAD", "1")
    monkeypatch.setenv("PIPELINE_VIDEO_TYPE", "shorts")
    monkeypatch.setattr(pipeline, "initialize_model_router", lambda **kw: "mock-model")
    monkeypatch.setattr(pipeline, "get_active_model", lambda: "mock-model")
    monkeypatch.setattr(pipeline, "research_topic", lambda *_: research)
    monkeypatch.setattr(pipeline, "write_script", lambda *a, **kw: script)
    monkeypatch.setattr(optimizer, "generate_optional", generator(proposals))
    seen = []
    monkeypatch.setattr(pipeline, "download_videos", lambda s, *a: seen.append(s) or {})
    monkeypatch.setattr(pipeline, "generate_narration", lambda *a: str(output / "audio.mp3"))
    monkeypatch.setattr(pipeline, "create_video", lambda *a, **kw: str(output / "final.mp4"))
    saved = Mock()
    monkeypatch.setattr(pipeline, "save_used_topic", saved)
    upload = Mock(side_effect=AssertionError("must not upload"))
    monkeypatch.setattr(pipeline, "upload_to_youtube", upload)
    monkeypatch.setattr(pipeline, "_create_thumbnail", lambda *_: "")
    pipeline.run()
    upload.assert_not_called()
    saved.assert_called_once_with(research["source_trend"])
    assert not (output / "stale.txt").exists()
    assert history.read_text() == "persistent history"
    written = json.loads((output / "script.json").read_text())
    assert seen == [written]
    assert (output / "content_quality_report.json").exists() is enabled
    assert bool(written.get("optimized_metadata")) is enabled


@pytest.mark.parametrize("optimized", [True, False])
def test_uploader_payload_and_thumbnail_failure(monkeypatch, tmp_path, script, optimized):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")
    script["optimized_metadata"] = optimized
    script["hashtags"] = ["##Shorts", "#Shorts", "#Artemis"]
    monkeypatch.setattr(youtube, "_get_credentials", lambda: types.SimpleNamespace(token="fake-token"))
    start = Mock(return_value="mock-session")
    monkeypatch.setattr(youtube, "_start_resumable_upload", start)
    monkeypatch.setattr(youtube, "_upload_video_chunks", lambda *a: {"id": "mock-id"})
    monkeypatch.setattr(youtube, "_render_thumbnail", Mock(side_effect=OSError("private")))
    thumb = Mock()
    monkeypatch.setattr(youtube, "_set_thumbnail", thumb)
    assert youtube.upload_to_youtube(script, str(video)).endswith("mock-id")
    body = start.call_args.args[1]
    assert body["status"]["privacyStatus"] == youtube.config.VIDEO_PRIVACY
    description = body["snippet"]["description"]
    if optimized:
        assert "##" not in description and description.count("#Shorts") == 1
    else:
        assert "##Shorts" in description  # Explicit legacy compatibility.
    thumb.assert_not_called()


def test_thumbnail_media_reuse_and_text(monkeypatch, tmp_path, script):
    monkeypatch.setattr(youtube.config, "OUTPUT_DIR", str(tmp_path))
    image = tmp_path / "source.png"
    Image.new("RGB", (640, 360), (200, 100, 20)).save(image)
    monkeypatch.setattr(youtube, "_find_source_image", lambda: image)
    script["thumbnail_text"] = "flight plan"
    result = youtube._create_thumbnail(script)
    with Image.open(result) as rendered:
        assert rendered.size == (1080, 1920)
    assert image.exists()


def test_trend_diagnostics_does_not_change_ranking(monkeypatch, tmp_path):
    from agents import us_trends
    rows = [{"video_id": "1", "title": "Artemis mission", "views": 100, "likes": 2,
             "comments": 1, "published_at": "2026-10-08T00:00:00Z"}]
    monkeypatch.setattr(us_trends, "_source_specs", lambda: [("mock", {})])
    monkeypatch.setattr(us_trends, "_fetch_source", lambda *a: ("mock", rows))
    monkeypatch.setattr(us_trends.config, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(us_trends.config, "YT_TREND_DIAGNOSTICS_ENABLED", False)
    before = us_trends.fetch_youtube_candidates()
    monkeypatch.setattr(us_trends.config, "YT_TREND_DIAGNOSTICS_ENABLED", True)
    after = us_trends.fetch_youtube_candidates()
    assert before == after
    assert (tmp_path / "trend_diagnostics.json").exists()


def test_thumbnail_corrupt_media_falls_back(monkeypatch, tmp_path, script):
    monkeypatch.setattr(youtube.config, "OUTPUT_DIR", str(tmp_path))
    bad = tmp_path / "corrupt.png"
    bad.write_bytes(b"not an image")
    monkeypatch.setattr(youtube, "_find_source_image", lambda: bad)
    script.update(video_type="long", thumbnail_text="flight plan")
    path = youtube._create_thumbnail(script)
    with Image.open(path) as result:
        assert result.size == (1280, 720)


def test_thumbnail_application_denial_is_sanitized(monkeypatch, tmp_path, capsys):
    image = tmp_path / "thumbnail.jpg"
    image.write_bytes(b"image")
    response = types.SimpleNamespace(status_code=403, json=lambda: {"secret": "private-value"})
    monkeypatch.setattr(youtube.requests, "post", Mock(return_value=response))
    assert youtube._set_thumbnail("id", str(image), "fake-token") is False
    assert "private-value" not in capsys.readouterr().out


@pytest.mark.parametrize("duration,band", [("PT30S", "under_3m"), ("PT6M", "3m_to_15m"), ("PT1H", "over_15m"), ("missing", None)])
def test_discovery_diagnostics_reuses_request(monkeypatch, duration, band):
    from agents import us_trends
    monkeypatch.setattr(us_trends.config, "YT_TREND_DIAGNOSTICS_ENABLED", True)
    monkeypatch.setattr(us_trends, "_age_hours", lambda *_: 1)
    request = Mock(return_value={"items": [{"id": "id", "snippet": {"title": "Artemis lunar mission", "publishedAt": "2026-10-08T00:00:00Z", "channelId": "channel"}, "statistics": {"viewCount": "100"}, "contentDetails": {"duration": duration}}]})
    monkeypatch.setattr(us_trends, "youtube_request", request)
    _, rows = us_trends._fetch_source("mock", {})
    assert request.call_count == 1
    assert rows[0].get("video_type") == band
    assert rows[0]["channel_id"] == "channel"
    assert rows[0]["observed_statistics"] == ["views"]
