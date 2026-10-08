"""Offline contracts for optional generation, rejection, rollback and metadata."""
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from agents.content_optimization import optimizer as opt
from agents.content_optimization.hooks import score_hook
from agents.content_optimization.titles import evaluate_title, valid_thumbnail
from agents.content_optimization.seo import normalize_tags, normalize_hashtags, upload_description
from agents.content_optimization.quality import validate_change, word_count, sanitize, sentences
from agents.topic_validation import validate_script_topic_lock


@pytest.fixture
def research():
    return {"topic": "Artemis lunar mission", "source_trend": "Artemis lunar mission",
            "video_title": "Artemis lunar mission overview", "content_domain": "GENERAL_TREND",
            "content_type": "EXPLAINER"}


@pytest.fixture
def script(research):
    narrations = [
        "The Artemis lunar mission is the subject of this explanation today. The flight plan gives us useful context for understanding the mission.",
        "The Artemis lunar mission flight plan explains the journey and its purpose. Understanding this context helps viewers separate the stated plans from speculation about what could happen later in the journey.",
        "That is the Artemis lunar mission context and the flight plan explained. Follow for more clear explanations of current topics.",
    ]
    sections = []
    for i, text in enumerate(narrations, 1):
        sections.append({"id": i, "section_type": ("hook", "explanation", "CTA")[i-1],
                         "title": "Artemis mission", "narration": text,
                         **{key: "Artemis lunar mission footage " + str(n) for n, key in enumerate(("video_query", "video_query_2", "video_query_3", "video_query_4"))},
                         "caption_text": "Artemis lunar mission", "bullet_points": [], "duration_seconds": 10})
    return {**research, "title": "The Artemis lunar mission and the context behind its detailed flight plan",
            "description": "Artemis lunar mission context", "tags": ["Artemis lunar mission", "#Shorts"],
            "video_type": "shorts", "sections": sections}


@pytest.fixture
def proposals():
    return {"hooks": ["What does the Artemis lunar mission flight plan mean for you?",
                      "How does the Artemis lunar mission flight plan explain the journey?",
                      "The Artemis lunar mission flight plan explains the journey and its purpose.",
                      "Why does the Artemis lunar mission flight plan need context?",
                      "What can the Artemis lunar mission flight plan tell you?"],
            "titles": ["Artemis lunar mission explained", "Artemis lunar mission flight plan",
                       "Artemis lunar mission context", "The Artemis lunar mission journey",
                       "Artemis lunar mission: What to know"],
            "description": "Artemis lunar mission explained.\nUnderstand the Artemis lunar mission flight plan and its context.",
            "thumbnail_text": "flight plan", "tags": ["Artemis lunar mission", "#Artemis lunar mission"],
            "search_queries": ["Artemis lunar mission explained"]}


def generator(proposals, approve=True):
    ids = [f"{kind}_{i}" for kind in ("hooks", "titles", "tags", "search_queries") for i in range(len(proposals.get(kind, [])))]
    ids += ["description", "thumbnail_text"]
    return Mock(side_effect=[json.dumps(proposals), json.dumps({"approved_ids": ids if approve else []})])


def report(tmp_path):
    return json.loads((tmp_path / "content_quality_report.json").read_text(encoding="utf-8"))


def test_enabled_optimization_and_report(script, research, proposals, tmp_path):
    original = copy.deepcopy(script)
    model = generator(proposals)
    result = opt.optimize_content(script, research, tmp_path, enabled=True, generate=model)
    assert result["sections"][0]["narration"] != script["sections"][0]["narration"]
    assert result["title"] == proposals["titles"][0]
    assert result["thumbnail_text"] == "flight plan"
    assert result["optimized_metadata"] is True
    assert result["tags"] == ["Artemis lunar mission"]
    assert result["hashtags"][0] == "#Shorts"
    assert model.call_count == 2
    assert script == original
    assert 70 <= word_count(result) <= 85
    validate_change(result, original, research)
    data = report(tmp_path)
    assert len(data["hook_candidates"]) == 5
    assert len(data["title_evaluations"]) == 5
    assert data["final_title"] == result["title"]
    assert data["topic_lock_validation"] == data["video_query_validation"] == "passed"
    assert data["generation_calls"] == 2


def test_disabled_identity(script, research, tmp_path, monkeypatch):
    monkeypatch.setattr(opt.config, "YT_OPTIMIZATION_ENABLED", False)
    model = Mock(side_effect=AssertionError("no API"))
    assert opt.optimize_content(script, research, tmp_path, generate=model) is script
    model.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("error", [TimeoutError("secret-error"), RuntimeError("secret-error"), ValueError("secret-error")])
def test_request_failure_preserves_valid_content(script, research, tmp_path, error, capsys):
    model = Mock(side_effect=error)
    assert opt.optimize_content(script, research, tmp_path, enabled=True, generate=model) == script
    assert model.call_count == 1
    assert "secret-error" not in capsys.readouterr().out
    assert "secret-error" not in json.dumps(report(tmp_path))


def test_review_failure_rejects_all(script, research, proposals, tmp_path):
    model = Mock(side_effect=[json.dumps(proposals), TimeoutError("private")])
    assert opt.optimize_content(script, research, tmp_path, enabled=True, generate=model) == script
    assert all(not x["approved"] for x in report(tmp_path)["hook_candidates"])


@pytest.mark.parametrize("bad", ["Chocolate cake is a tasty dessert?", "Artemis lunar mission reached 999 planets?", "Artemis lunar mission <script>?"])
def test_deterministic_rejection_even_if_review_approves(script, research, proposals, tmp_path, bad):
    proposals["hooks"] = [bad] * 5
    result = opt.optimize_content(script, research, tmp_path, enabled=True, generate=generator(proposals))
    assert result["sections"] == script["sections"]
    assert all(not h["approved"] for h in report(tmp_path)["hook_candidates"])


def test_semantic_rejection_of_unsupported_claim(script, research, proposals, tmp_path):
    proposals["hooks"] = ["Why did the Artemis lunar mission fail catastrophically?"] * 5
    result = opt.optimize_content(script, research, tmp_path, enabled=True, generate=generator(proposals, False))
    assert result == script


@pytest.mark.parametrize("raw", ["not json", "[]", "null", '{"hooks":null}', '{"hooks":[1,2,3,4,5]}'])
def test_malformed_output_falls_back(script, research, tmp_path, raw):
    result = opt.optimize_content(script, research, tmp_path, enabled=True, generate=Mock(return_value=raw))
    assert result == script


def test_long_structure_and_queries_preserved(script, research, proposals, tmp_path):
    base = copy.deepcopy(script["sections"][1])
    script["video_type"] = "long"
    script["sections"] = []
    for i in range(9):
        row = copy.deepcopy(base)
        row["id"] = i + 1
        row["section_type"] = "hook" if i == 0 else "CTA" if i == 8 else "explanation"
        row["narration"] = "The Artemis lunar mission is the subject of this explanation today. " + " ".join(["context"] * 96) + "."
        script["sections"].append(row)
    assert 920 <= word_count(script) <= 1100
    result = opt.optimize_content(script, research, tmp_path, enabled=True, generate=generator(proposals))
    validate_change(result, script, research)
    assert len(result["sections"]) == 9
    for old, new in zip(script["sections"], result["sections"]):
        assert {k: v for k, v in old.items() if k != "narration"} == {k: v for k, v in new.items() if k != "narration"}


def test_word_budget_rollback_leaves_other_features(script, research, proposals, tmp_path):
    proposals["hooks"] = ["What Artemis lunar mission?"] * 5
    # Bring original to the lower bound; a shorter hook must be rolled back.
    extra = word_count(script) - 70
    script["sections"][1]["narration"] = " ".join(script["sections"][1]["narration"].split()[:-extra])
    result = opt.optimize_content(script, research, tmp_path, enabled=True, generate=generator(proposals))
    assert result["sections"] == script["sections"]
    assert result["title"] != script["title"]


def test_invalid_input_is_not_hidden(script, research, tmp_path):
    script["sections"][0]["video_query_4"] = "Chocolate cakes"
    with pytest.raises(ValueError):
        opt.optimize_content(script, research, tmp_path, enabled=True, generate=Mock())


@pytest.mark.parametrize("field", ["topic", "source_trend", "video_type", "content_domain"])
def test_identity_guard(script, research, field):
    changed = copy.deepcopy(script)
    changed[field] = "other"
    with pytest.raises(ValueError):
        validate_change(changed, script, research)


def test_hook_scores_are_weakest_link_heuristics():
    good = score_hook("What does the Artemis lunar mission flight plan mean for you?", "Artemis lunar mission")
    bad = score_hook("Welcome to this amazing insane shocking channel", "Artemis lunar mission")
    assert good["score"] > bad["score"]
    values = list(good["properties"].values())
    assert good["score"] == round(.6 * sum(values) / 5 + .4 * min(values))


@pytest.mark.parametrize("title", ["", "Chocolate cakes explained", "ARTEMIS LUNAR MISSION EXPLAINED", "Artemis lunar mission shocking secret revealed", "Artemis lunar mission " + "x" * 100])
def test_bad_title(title):
    assert not evaluate_title(title, "Artemis lunar mission")["valid"]


def test_mobile_title_and_thumbnail():
    assert "mobile_truncation_risk" in evaluate_title("Artemis lunar mission: understanding the flight plan", "Artemis lunar mission")["issues"]
    assert valid_thumbnail("flight plan", "Artemis lunar mission", "The flight plan is explained")
    assert not valid_thumbnail("Artemis lunar mission", "Artemis lunar mission", "Artemis lunar mission")
    assert not valid_thumbnail("an invented space catastrophe", "Artemis lunar mission", "flight plan")


def test_seo_normalization():
    assert normalize_tags(["##Artemis lunar mission", "artemis lunar mission", "cakes", None], "Artemis lunar mission") == ["Artemis lunar mission"]
    assert normalize_hashtags(["##Shorts", "#shorts", "##Artemis", "Artemis"], True) == ["#Shorts", "#Artemis"]
    assert normalize_hashtags(["#Shorts", "Artemis"], False) == ["#Artemis"]
    text = upload_description({"description": "Topic #Shorts ##Shorts", "hashtags": ["##Shorts", "#Artemis"], "video_type": "shorts"})
    assert text.count("#Shorts") == 1 and "##" not in text
    assert len(upload_description({"description": "x" * 9000})) <= 5000


def test_report_secrets_and_write_failure(script, research, proposals, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TEST_API_KEY", "private-example-value")
    assert "private-example-value" not in json.dumps(sanitize({"text": "private-example-value", "refresh_token": "foo"}))
    monkeypatch.setattr(Path, "write_text", Mock(side_effect=OSError("private-example-value")))
    result = opt.optimize_content(script, research, tmp_path, enabled=True, generate=generator(proposals))
    validate_script_topic_lock(result, research)
    assert "private-example-value" not in capsys.readouterr().out


@pytest.mark.parametrize("setting,expected", [("bad", 20), ("nan", 20), ("inf", 20), ("999", 60), ("-1", 1), ("5", 5)])
def test_timeout_clamped(setting, expected, monkeypatch):
    monkeypatch.setattr(opt.config, "YT_OPTIMIZATION_TIMEOUT_SECONDS", setting)
    assert opt._timeout() == expected


def test_optional_client_one_attempt(monkeypatch):
    from agents import gemini_client
    monkeypatch.setattr(gemini_client, "get_active_model", lambda: "existing-model")
    call = Mock(side_effect=TimeoutError("private"))
    monkeypatch.setattr(gemini_client, "_generate_once", call)
    with pytest.raises(TimeoutError):
        gemini_client.generate_optional("prompt", timeout_seconds=7)
    call.assert_called_once_with("existing-model", "prompt", timeout_seconds=7, max_output_tokens=3072)


def test_retention_prompt_is_flagged(research, monkeypatch):
    from agents import scriptwriter
    monkeypatch.setattr(scriptwriter.config, "YT_OPTIMIZATION_ENABLED", False)
    assert "RETENTION:" not in scriptwriter._write_script_prompt(research, "shorts")
    monkeypatch.setattr(scriptwriter.config, "YT_OPTIMIZATION_ENABLED", True)
    prompt = scriptwriter._write_script_prompt(research, "long")
    assert "RETENTION:" in prompt and "920-1100" in prompt and "exactly 9" in prompt


def test_pacing_removes_only_adjacent_repetition(script, research, tmp_path):
    sentence = "The Artemis lunar mission has useful context."
    script["sections"][1]["narration"] += " " + sentence + " " + sentence
    before = copy.deepcopy(script)
    result = opt.optimize_content(script, research, tmp_path, enabled=True, generate=Mock(return_value="{}"))
    assert result["sections"][1]["narration"].count(sentence) == 1
    assert 70 <= word_count(result) <= 85
    validate_change(result, before, research)


def test_title_no_improvement_retains_original(script, research, proposals, tmp_path):
    script["title"] = proposals["titles"][0]
    result = opt.optimize_content(script, research, tmp_path, enabled=True, generate=generator(proposals))
    assert result["title"] == script["title"]
    assert "original_title_retained" in report(tmp_path)["fallback_decisions"]


def test_abbreviation_does_not_split_hook():
    assert sentences("The U.S. lunar program has context. Here is why.") == ["The U.S. lunar program has context.", "Here is why."]


def test_report_final_validation_failure_restores_original(script, research, proposals, tmp_path, monkeypatch):
    monkeypatch.setattr(opt, "validate_change", Mock(side_effect=ValueError("blocked")))
    result = opt.optimize_content(script, research, tmp_path, enabled=True, generate=generator(proposals))
    assert result == script
    assert report(tmp_path)["final_title"] == script["title"]
