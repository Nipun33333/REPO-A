"""Synthetic credentials only; every service request is mocked."""
import json
import traceback
from unittest.mock import Mock
from urllib.parse import quote

import pytest
import requests

from agents import us_trends
from agents.safe_logging import SanitizedServiceError, safe_error_summary, safe_log_text
from tests.test_gemini_resilience import load_client


SECRETS = ["SYNTHETIC_KEY+/=ONLY", "SYNTHETIC_ACCESS_ONLY",
           "SYNTHETIC_REFRESH_ONLY", "SYNTHETIC_CLIENT_SECRET_ONLY"]


def unsafe_message():
    return ("https://example.invalid/videos?key=" + quote(SECRETS[0], safe="")
            + "&access_token=" + SECRETS[1] + "&refresh_token=" + SECRETS[2]
            + " Authorization: Bearer " + SECRETS[1]
            + " client_secret=" + SECRETS[3] + " raw_key=" + SECRETS[0])


def assert_safe(text):
    for secret in SECRETS:
        assert secret not in text
        assert quote(secret, safe="") not in text
    assert "example.invalid" not in text
    assert "?key=" not in text and "&key=" not in text


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "request", Mock(side_effect=AssertionError("Network disabled")))


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_request_error_never_exposes_url_or_chained_exception(monkeypatch, status):
    response = requests.Response()
    response.status_code = status
    response.url = unsafe_message()
    monkeypatch.setattr(us_trends.config, "YOUTUBE_API_KEY", SECRETS[0])
    get = Mock(return_value=response)
    monkeypatch.setattr(us_trends.requests, "get", get)
    with pytest.raises(SanitizedServiceError) as caught:
        us_trends.youtube_request("videos", {"chart": "mostPopular"})
    assert str(caught.value) == f"HTTPError (HTTP {status})"
    assert caught.value.__suppress_context__ is True
    assert_safe("".join(traceback.format_exception(caught.value)))
    assert get.call_count == 1


@pytest.mark.parametrize("error_class", [requests.Timeout, requests.ConnectionError, requests.exceptions.SSLError, ValueError])
def test_transport_and_json_failures_are_safe(monkeypatch, error_class):
    monkeypatch.setattr(us_trends.config, "YOUTUBE_API_KEY", SECRETS[0])
    error = error_class(unsafe_message())
    if error_class is ValueError:
        response = Mock()
        response.json.side_effect = error
        get = Mock(return_value=response)
    else:
        get = Mock(side_effect=error)
    monkeypatch.setattr(us_trends.requests, "get", get)
    with pytest.raises(SanitizedServiceError) as caught:
        us_trends.youtube_request("videos", {})
    assert type(error).__name__ in str(caught.value)
    assert_safe("".join(traceback.format_exception(caught.value)))


def test_request_success_preserves_params_and_result(monkeypatch):
    monkeypatch.setattr(us_trends.config, "YOUTUBE_API_KEY", SECRETS[0])
    data = {"items": []}
    response = Mock()
    response.json.return_value = data
    get = Mock(return_value=response)
    monkeypatch.setattr(us_trends.requests, "get", get)
    params = {"chart": "mostPopular"}
    assert us_trends.youtube_request("videos", params, timeout=4) is data
    assert params == {"chart": "mostPopular"}
    assert get.call_args.kwargs["params"] == {**params, "key": SECRETS[0]}
    assert get.call_args.kwargs["timeout"] == 4


def test_source_failure_is_safe_and_other_source_still_works(monkeypatch, capsys):
    response = requests.Response()
    response.status_code = 403
    failure = requests.HTTPError(unsafe_message(), response=response)
    monkeypatch.setattr(us_trends, "_source_specs", lambda: [("failed", {}), ("working", {})])
    monkeypatch.setattr(us_trends.config, "YT_TREND_DIAGNOSTICS_ENABLED", False)
    item = {"video_id": "good", "title": "Artemis lunar mission", "views": 200, "likes": 5, "comments": 1}
    def fetch(name, params):
        if name == "failed":
            raise failure
        return name, [item]
    monkeypatch.setattr(us_trends, "_fetch_source", fetch)
    assert us_trends.fetch_youtube_candidates()[0]["video_id"] == "good"
    logs = capsys.readouterr().out
    assert "HTTPError (HTTP 403)" in logs and "working: 1" in logs
    assert_safe(logs)


def test_all_sources_fail_safely(monkeypatch, capsys):
    monkeypatch.setattr(us_trends, "_source_specs", lambda: [("source", {})])
    monkeypatch.setattr(us_trends, "_fetch_source", Mock(side_effect=requests.Timeout(unsafe_message())))
    monkeypatch.setattr(us_trends.config, "YT_TREND_DIAGNOSTICS_ENABLED", False)
    with pytest.raises(RuntimeError, match="Could not retrieve current YouTube discovery candidates") as caught:
        us_trends.get_best_us_trending_topic()
    assert_safe(capsys.readouterr().out + "".join(traceback.format_exception(caught.value)))


@pytest.mark.parametrize("operation", ["read", "write"])
def test_history_errors_do_not_print_exception_data(monkeypatch, capsys, operation):
    monkeypatch.setattr(us_trends.os.path, "exists", lambda *_: True)
    monkeypatch.setattr("builtins.open", Mock(side_effect=PermissionError(unsafe_message())))
    if operation == "read":
        assert us_trends.load_used_topics() == []
    else:
        us_trends.save_used_topic("Artemis lunar mission")
    logs = capsys.readouterr().out
    assert "PermissionError" in logs
    assert_safe(logs)


def test_research_history_error_is_sanitized(monkeypatch, capsys):
    from agents import researcher
    monkeypatch.setattr(researcher.os.path, "exists", lambda *_: True)
    monkeypatch.setattr("builtins.open", Mock(side_effect=OSError(unsafe_message())))
    assert researcher.load_banned_topics() == []
    assert_safe(capsys.readouterr().out)


def test_successful_research_redacts_logs_without_changing_content(monkeypatch, capsys):
    from agents import researcher
    monkeypatch.setattr(researcher, "load_banned_topics", lambda: [])
    monkeypatch.setattr(researcher, "get_best_us_trending_topic", lambda *_: {})
    data = {"topic": "Artemis lunar mission " + unsafe_message(),
            "video_title": "Artemis lunar mission", "content_domain": "GENERAL_TREND", "content_type": "EXPLAINER"}
    monkeypatch.setattr(us_trends.config, "YOUTUBE_API_KEY", SECRETS[0])
    monkeypatch.setattr(researcher, "_research_selected_candidate", lambda *a: data)
    assert researcher.research_topic("Broad US trends") is data
    assert_safe(capsys.readouterr().out)


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_selector_failure_is_sanitized(monkeypatch, error_type):
    monkeypatch.setattr(us_trends, "select_semantic_candidate", Mock(side_effect=error_type(unsafe_message())))
    with pytest.raises(SanitizedServiceError) as caught:
        us_trends.choose_best_trend([{"video_id": "candidate"}])
    assert_safe("".join(traceback.format_exception(caught.value)))


def test_untrusted_error_type_and_status_never_appear():
    error_class = type(SECRETS[0], (Exception,), {})
    error = error_class(unsafe_message())
    error.status_code = unsafe_message()
    assert safe_error_summary(error) == "Exception"


def test_error_summary_does_not_stringify_exception():
    class HostileError(Exception):
        def __str__(self):
            raise AssertionError("Do not inspect provider text")
    assert safe_error_summary(HostileError()) == "Exception"


def test_source_and_subject_log_redaction(monkeypatch):
    monkeypatch.setattr(us_trends.config, "YOUTUBE_API_KEY", SECRETS[0])
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", SECRETS[2])
    text = "Artemis lunar mission " + unsafe_message()
    safe = safe_log_text(text)
    assert safe.startswith("Artemis lunar mission")
    assert_safe(safe)


@pytest.mark.parametrize("message,expected_calls", [("403 PERMISSION_DENIED", 1), ("unrecognized failure", 1), ("503 UNAVAILABLE", 2)])
def test_gemini_discovery_retry_errors_and_status_are_sanitized(monkeypatch, capsys, message, expected_calls):
    client = load_client(monkeypatch)
    client.config.GEMINI_TASK_MAX_RETRIES = 0
    monkeypatch.setattr(client, "build_chain", lambda *_: ["model-a"])
    monkeypatch.setattr("time.sleep", lambda *_: None)
    failure = RuntimeError(message + " " + unsafe_message())
    generate = Mock(side_effect=failure)
    monkeypatch.setattr(client, "_generate_once", generate)
    with pytest.raises(RuntimeError) as caught:
        client.generate("discovery prompt")
    assert generate.call_count == expected_calls
    assert_safe(capsys.readouterr().out + "".join(traceback.format_exception(caught.value)))
    assert_safe(json.dumps(client.get_model_status()))
