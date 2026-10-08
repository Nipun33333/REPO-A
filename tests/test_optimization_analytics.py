from datetime import datetime, timezone
import json
import subprocess
import sys

import pytest

from agents.content_optimization.trends import analyze_trends, save_trend_diagnostics
from agents.content_optimization.retention import analyze_csv
from agents.content_optimization.retention import main as retention_main


def candidate():
    return {"video_id": "current", "channel_id": "stable-channel", "video_type": "under_3m",
            "published_at": "2026-01-01T00:00:00Z", "views": 1000, "likes": 20, "comments": 5}


def history():
    return [{"video_id": str(i), "channel_id": "stable-channel", "video_type": "under_3m",
             "age_hours": 24, "views": views} for i, views in enumerate([100, 200, 300, 400])]


def analyze(c, h):
    return analyze_trends([c], h, now=datetime(2026, 1, 2, tzinfo=timezone.utc))["videos"][0]


def test_real_relative_median():
    row = analyze(candidate(), history())
    assert row["historical_median"] == 250
    assert row["relative_performance"] == 4
    assert row["outlier"] is True
    assert row["views_per_hour"] == 41.67
    assert row["engagement_rate"] == .025


@pytest.mark.parametrize("change", ["thin", "duplicate", "different_channel", "different_format", "different_age", "zero", "self"])
def test_incomparable_history_skipped(change):
    rows = history()
    if change == "thin": rows.pop()
    if change == "duplicate": rows[-1]["video_id"] = rows[0]["video_id"]
    if change == "different_channel": rows[-1]["channel_id"] = "other"
    if change == "different_format": rows[-1]["video_type"] = "over_15m"
    if change == "different_age": rows[-1]["age_hours"] = 500
    if change == "zero":
        for r in rows: r["views"] = 0
    if change == "self": rows[-1]["video_id"] = "current"
    assert "relative_performance" not in analyze(candidate(), rows)


def test_missing_data_not_invented():
    row = analyze({"views": 0, "likes": 0, "comments": 0, "observed_statistics": []}, [])
    assert "views_per_hour" not in row and "engagement_rate" not in row
    assert "relative_performance" not in row


def test_optional_history_error_nonblocking(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("not json")
    save_trend_diagnostics([candidate()], tmp_path, str(path))
    assert "unavailable" in capsys.readouterr().out
    save_trend_diagnostics([candidate()], tmp_path)
    assert json.loads((tmp_path / "trend_diagnostics.json").read_text())["videos"]


def csv_file(tmp_path, data):
    path = tmp_path / "retention.csv"
    # Preserve explicit LF/CRLF fixtures; Windows text translation would double CR.
    path.write_bytes(data.encode("utf-8"))
    return path


def test_short_seconds_not_guessed_as_percent(tmp_path):
    path = csv_file(tmp_path, "position,retention\n0,100\n10,95\n20,90\n30,70\n40,65\n")
    report = analyze_csv(path)
    assert report["opening_retention_percent"] == 70
    assert report["opening_drop_percentage_points"] == 30
    assert report["cliffs"][0]["from_seconds"] == 20


def test_fraction_percent_axis_interpolation(tmp_path):
    path = csv_file(tmp_path, "position,retention\n0,1\n50,.8\n100,.6\n")
    result = analyze_csv(path, axis="percent", duration=120, retention_unit="fraction")
    assert result["opening_retention_percent"] == 90
    assert result["cliffs"][0]["to_seconds"] == 60


@pytest.mark.parametrize("data", ["position,retention\n0,100\n0,80\n", "position,retention\n1,nan\n2,90\n", "position,retention\n-1,100\n2,80\n", "wrong,columns\n0,100\n1,90\n", "position,retention\n0,100\n"])
def test_retention_invalid(data, tmp_path):
    with pytest.raises(ValueError):
        analyze_csv(csv_file(tmp_path, data))


def test_percent_requires_duration_and_allows_rewatching(tmp_path):
    path = csv_file(tmp_path, "position,retention\n0,130\n50,110\n100,90\n")
    with pytest.raises(ValueError):
        analyze_csv(path, axis="percent")
    assert analyze_csv(path, axis="percent", duration=60)["opening_retention_percent"] == 110


@pytest.mark.parametrize("row,detail", [
    ("10", "two cells"),
    ("10,", "retention is missing or empty"),
    ("10,   ", "retention is missing or empty"),
    ("10,not-a-number", "retention must be numeric"),
    ("10,90,extra", "two cells"),
    (",90", "position is missing or empty"),
    ("bad-position,90", "position must be numeric"),
    ("10,NaN", "retention must be numeric"),
    ("10,Infinity", "retention must be numeric"),
    ("10,-1", "retention must be a finite, non-negative number"),
    ("10,1e999", "retention must be a finite, non-negative number"),
    ("10,90%%", "retention must be numeric"),
    ("10,1_000", "retention must be numeric"),
    ("", "two cells"),
    ('10,"90', "malformed CSV"),
    ('10,"90"oops', "malformed CSV"),
])
def test_retention_bad_rows_report_line_without_traceback(tmp_path, monkeypatch, capsys, row, detail):
    path = csv_file(tmp_path, "position,retention\n0,100\n" + row + "\n")
    with pytest.raises(ValueError, match="Row 3") as caught:
        analyze_csv(path)
    assert detail in str(caught.value)
    monkeypatch.setattr(sys, "argv", ["retention", str(path)])
    with pytest.raises(SystemExit) as exit_info:
        retention_main()
    assert exit_info.value.code == 2
    output = capsys.readouterr()
    assert "Row 3" in output.err and detail in output.err
    assert "Traceback" not in output.err and not output.out


@pytest.mark.parametrize("data,kwargs", [
    ("position,retention\n0,100\n30,70\n60,50\n", {}),
    ('position,retention\n"0","100%"\n"30","70%"\n"60","50%"\n', {}),
    ("position,retention\r\n0,1\r\n30,.7\r\n60,.5\r\n", {"retention_unit": "fraction"}),
    ("\ufeffposition,retention\n0%,100\n50%,70\n100%,50\n", {"axis": "percent", "duration": 60}),
])
def test_retention_valid_formats_preserve_analytics(tmp_path, data, kwargs):
    result = analyze_csv(csv_file(tmp_path, data), **kwargs)
    assert result["samples"] == 3
    assert result["opening_retention_percent"] == 70
    assert result["opening_drop_percentage_points"] == 30
    assert result["cliffs"][0]["drop_percentage_points"] == 30
    assert result["middle_loss_points_per_second"] == pytest.approx(20/30)


@pytest.mark.parametrize("data,args,detail", [
    ("", [], "Row 1"),
    ("wrong,columns\n0,100\n", [], "Row 1"),
    ("position,retention\n0,100\n0,90\n", [], "Row 3: positions must increase"),
    ("position,retention\n0,100\n101,90\n", ["--axis", "percent", "--duration", "60"], "Row 3: percent position"),
    ("position,retention\n0,1\n30,.7%\n", ["--retention-unit", "fraction"], "Row 3: retention must be numeric"),
    ("position,retention\n0,1\n30,1e308\n", ["--retention-unit", "fraction"], "Row 3: value is too large"),
])
def test_retention_cli_expected_validation_errors(tmp_path, monkeypatch, capsys, data, args, detail):
    path = csv_file(tmp_path, data)
    monkeypatch.setattr(sys, "argv", ["retention", str(path), *args])
    with pytest.raises(SystemExit) as caught:
        retention_main()
    assert caught.value.code == 2
    error = capsys.readouterr().err
    assert detail in error and "Traceback" not in error


@pytest.mark.parametrize("kind", ["missing_file", "invalid_encoding"])
def test_retention_cli_file_errors(tmp_path, monkeypatch, capsys, kind):
    path = tmp_path / "input.csv"
    if kind == "invalid_encoding":
        path.write_bytes(b"position,retention\n0,100\n1,\xff\n")
    monkeypatch.setattr(sys, "argv", ["retention", str(path)])
    with pytest.raises(SystemExit) as caught:
        retention_main()
    assert caught.value.code == 2
    error = capsys.readouterr().err
    assert ("UTF-8" if kind == "invalid_encoding" else "Cannot read") in error
    assert "Traceback" not in error


def test_retention_real_cli_process_valid_and_invalid(tmp_path):
    path = csv_file(tmp_path, "position,retention\n0,100\n30,70\n")
    command = [sys.executable, "-m", "agents.content_optimization.retention", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0
    assert json.loads(result.stdout)["opening_retention_percent"] == 70
    path.write_text("position,retention\n0,100\n30\n", encoding="utf-8")
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert result.returncode == 2 and "Row 3" in result.stderr
    assert "Traceback" not in result.stderr
