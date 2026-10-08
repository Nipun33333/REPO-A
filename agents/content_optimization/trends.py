"""Read-only diagnostics; never use popularity-biased discovery as a baseline."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from .quality import sanitize


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


def analyze_trends(candidates, history=(), now=None):
    """Historical rows require stable channel IDs, format and observation age.

    Comparable = same channel + format + within 25% of exposure age. Require
    four unique historical videos, excluding the candidate, and positive median.
    No API calls. Missing statistics remain missing, never become fake zeros.
    """
    now = now or datetime.now(timezone.utc)
    results = []
    for candidate in candidates:
        candidate = dict(candidate)
        if "observed_statistics" in candidate:
            for field in ("views", "likes", "comments"):
                if field not in candidate["observed_statistics"]:
                    candidate.pop(field, None)
        row = {"video_id": candidate.get("video_id"), "title": candidate.get("title", "")}
        views = _number(candidate.get("views"))
        age = None
        try:
            published = datetime.fromisoformat(candidate["published_at"].replace("Z", "+00:00"))
            age = (now - published).total_seconds() / 3600
            if age <= 0:
                age = None
        except (KeyError, ValueError, TypeError):
            pass
        if views is not None and age:
            row["views_per_hour"] = round(views / age, 2)
            row["age_hours"] = round(age, 2)
        likes, comments = _number(candidate.get("likes")), _number(candidate.get("comments"))
        if views and likes is not None and comments is not None:
            row["engagement_rate"] = round((likes + comments) / views, 5)
        comparable = {}
        for old in history:
            old_views, old_age = _number(old.get("views")), _number(old.get("age_hours"))
            if (candidate.get("channel_id") and candidate.get("video_type") and age
                    and old.get("channel_id") == candidate["channel_id"]
                    and old.get("video_type") == candidate["video_type"]
                    and old.get("video_id") and old["video_id"] != candidate.get("video_id")
                    and old_views is not None and old_age is not None
                    and .75 * age <= old_age <= 1.25 * age):
                comparable[old["video_id"]] = old_views
        row["comparable_count"] = len(comparable)
        baseline = median(comparable.values()) if len(comparable) >= 4 else 0
        if baseline > 0 and views is not None:
            row.update({"historical_median": baseline, "relative_performance": round(views / baseline, 2),
                        "outlier": views / baseline >= 2,
                        "title_pattern": "question" if candidate.get("title", "").endswith("?") else "statement"})
        else:
            row["relative_performance_skipped"] = "insufficient_comparable_history"
        results.append(row)
    return {"videos": results, "note": "Observed correlations only; no trend ranking changes or causal claims."}


def save_trend_diagnostics(candidates, output_dir, history_path=""):
    try:
        history = []
        if history_path:
            path = Path(history_path)
            if path.stat().st_size > 5_000_000:
                raise ValueError("history_too_large")
            history = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(history, list) or any(not isinstance(r, dict) for r in history):
                raise ValueError("history_shape")
        report = analyze_trends(candidates, history)
        path = Path(output_dir) / "trend_diagnostics.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sanitize(report), indent=2, allow_nan=False), encoding="utf-8")
    except Exception:
        print("   Optional trend diagnostics unavailable; discovery continues.")
