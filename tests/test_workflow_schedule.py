from pathlib import Path
import re
from datetime import datetime, timedelta, timezone
import types
import pytest
from pipeline_runtime import get_video_type


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily-short.yml"
CONFIG = ROOT / "config.py"
ENV_EXAMPLE = ROOT / ".env.example"
PIPELINE = ROOT / "pipeline.py"
README = ROOT / "README.md"
SETUP = ROOT / "SETUP.md"


def test_timezone_aware_schedule_is_exact():
    text = WORKFLOW.read_text(encoding="utf-8")
    expected = ['0 1 * * *', '0 3 * * *', '0 6 * * *']
    assert re.findall(r'cron: "([^"\n]+)"', text) == expected
    assert text.count('timezone: "Asia/Kolkata"') == 3
    assert 'PIPELINE_VIDEO_TYPE: shorts' in text
    assert 'PIPELINE_VIDEO_TYPE=long' not in text
    assert 'MANUAL_VIDEO_TYPE' not in text
    assert 'options:' not in text


def test_public_upload_is_explicit():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    config = CONFIG.read_text(encoding="utf-8")
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "VIDEO_PRIVACY: public" in workflow
    assert 'VIDEO_PRIVACY = os.getenv("VIDEO_PRIVACY", "public")' in config
    assert "VIDEO_PRIVACY=public" in env_example


def test_production_runs_are_serialized():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "concurrency:" in text
    assert "group: daily-youtube-pipeline" in text
    assert "cancel-in-progress: false" in text


def test_pipeline_comments_match_timezone_aware_schedule():
    text = PIPELINE.read_text(encoding="utf-8")
    assert "workflow schedule itself is explicitly" in text
    assert "UTC is what the cron trigger fires on" not in text


def test_docs_contain_current_schedule():
    for path in (README, SETUP):
        text = path.read_text(encoding="utf-8")
        assert "1:00 AM IST" in text
        assert "3:00 AM IST" in text
        assert "6:00 AM IST" in text
        assert "Monday-Sunday" in text
        assert "5:00 PM IST" not in text


@pytest.mark.parametrize("day", range(7))
@pytest.mark.parametrize("hour", [1, 3, 6])
def test_all_21_weekly_slots_resolve_to_shorts(monkeypatch, day, hour):
    monkeypatch.delenv("PIPELINE_VIDEO_TYPE", raising=False)
    ist = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 10, 12, hour, tzinfo=ist) + timedelta(days=day)
    assert get_video_type(local) == "shorts"
    assert get_video_type(local.astimezone(timezone.utc)) == "shorts"


@pytest.mark.parametrize("mode", ["long", "normal", "auto", "invalid"])
def test_cli_and_script_cannot_generate_long_videos(monkeypatch, mode):
    from agents.scriptwriter import write_script
    monkeypatch.setenv("PIPELINE_VIDEO_TYPE", mode)
    with pytest.raises(ValueError, match="Only Shorts"):
        get_video_type()
    with pytest.raises(ValueError, match="Only YouTube Shorts"):
        write_script({}, video_type=mode)


@pytest.mark.parametrize("mode", ["long", "normal"])
def test_gui_rejects_long_generation(monkeypatch, mode):
    import gui
    monkeypatch.setitem(gui._state, "running", False)
    monkeypatch.setattr(gui, "request", types.SimpleNamespace(get_json=lambda **_: {"video_type": mode}))
    monkeypatch.setattr(gui, "jsonify", lambda data: data)
    result, status = gui.run_pipeline()
    assert status == 400 and result["ok"] is False


def test_gui_has_only_short_format():
    text = (ROOT / "gui_templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="fmt-normal"' not in text
    assert "const _videoType = 'shorts';" in text
