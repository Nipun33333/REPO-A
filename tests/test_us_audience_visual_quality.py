"""Offline regressions for US topic choice and strictly relevant video footage."""
import ast
from pathlib import Path
from agents import us_trends


def test_subject_free_source_titles_are_rejected():
    for title in ("This Sucks", "We Won", "The Internet Exploded Over This", "WOW!"):
        assert not us_trends.has_specific_subject({"title": title}), title
    for title in ("Demon Slayer ep 43", "Why Binding of Isaac Music Changed",
                  "BIGBANG GiiiRIP", "ドラゴンボール 新予告"):
        assert us_trends.has_specific_subject({"title": title}), title


def test_downloaded_video_validation_not_bypassed():
    stock = ast.parse(Path("video/stock.py").read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(stock)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_post_download_validate"
    ]
    # Both Google/Tavily and Pexels videos must have a real post-download
    # vision check, not only a metadata/title check.
    assert len(calls) >= 2
    for call in calls:
        arguments = {kw.arg: kw.value for kw in call.keywords}
        assert "skip_visual_check" not in arguments or (
            isinstance(arguments["skip_visual_check"], ast.Constant)
            and arguments["skip_visual_check"].value is False
        )


def test_empty_sections_cannot_borrow_other_section_footage():
    stock = ast.parse(Path("video/stock.py").read_text(encoding="utf-8"))
    pipeline = next(
        node for node in stock.body
        if isinstance(node, ast.FunctionDef) and node.name == "download_videos"
    )
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "_fill_empty_sections_from_pool"
        for node in ast.walk(pipeline)
    )
    assert any(isinstance(node, ast.Raise) for node in ast.walk(pipeline))


def test_movie_anime_discovery_requires_us_region_signals():
    specs = us_trends._source_specs()
    assert specs
    assert all(params["regionCode"] == "US" for _, params in specs)
    assert any("anime" in name.lower() for name, _ in specs)
    assert any("movie" in name.lower() for name, _ in specs)


