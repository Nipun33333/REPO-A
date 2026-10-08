"""Offline CSV analysis: python -m agents.content_optimization.retention --help."""
import argparse
import csv
import json
import math
import re


def _number(value, field, row_number, *, allow_percent):
    value = value.strip()
    if not value:
        raise ValueError(f"Row {row_number}: {field} is missing or empty.")
    if allow_percent and value.endswith("%"):
        value = value[:-1].strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
        raise ValueError(f"Row {row_number}: {field} must be numeric in the selected units.")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Row {row_number}: {field} must be a finite, non-negative number.")
    return number


def _read_points(path, axis, duration, retention_unit):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        # Strict parsing detects broken quoting; csv.reader also exposes blank rows
        # and extra/missing cells instead of silently discarding them.
        reader = csv.reader(handle, strict=True)
        try:
            if next(reader, None) != ["position", "retention"]:
                raise ValueError("Row 1: CSV needs exactly position,retention columns; choose units explicitly.")
            for cells in reader:
                row_number = reader.line_num
                if len(cells) != 2:
                    raise ValueError(f"Row {row_number}: expected exactly two cells: position and retention.")
                x = _number(cells[0], "position", row_number, allow_percent=axis == "percent")
                y = _number(cells[1], "retention", row_number, allow_percent=retention_unit == "percent")
                if axis == "percent":
                    if x > 100:
                        raise ValueError(f"Row {row_number}: percent position must be between 0 and 100.")
                    x = x / 100 * duration
                if retention_unit == "fraction":
                    y *= 100
                if not math.isfinite(x) or not math.isfinite(y):
                    raise ValueError(f"Row {row_number}: value is too large after unit conversion.")
                if rows and x <= rows[-1][0]:
                    raise ValueError(f"Row {row_number}: positions must increase strictly.")
                rows.append((x, y))
        except csv.Error:
            raise ValueError(f"Row {max(1, reader.line_num)}: malformed CSV; check quoting and delimiters.") from None
    return rows


def analyze_csv(path, *, axis="seconds", duration=None, retention_unit="percent"):
    if axis not in {"seconds", "percent"} or retention_unit not in {"percent", "fraction"}:
        raise ValueError("Unsupported units")
    if axis == "percent" and (duration is None or not math.isfinite(duration) or duration <= 0):
        raise ValueError("Percent position requires a positive duration in seconds")
    rows = _read_points(path, axis, duration, retention_unit)
    if len(rows) < 2:
        raise ValueError("At least two retention samples are required")
    # No guessing percent vs seconds; shorts under 100s remain seconds.
    cutoff = min(30, rows[-1][0])
    opening = None
    for (x0, y0), (x1, y1) in zip(rows, rows[1:]):
        if x0 <= cutoff <= x1:
            opening = y0 + (y1 - y0) * (cutoff - x0) / (x1 - x0)
            break
    cliffs = [{"from_seconds": a[0], "to_seconds": b[0], "drop_percentage_points": round(a[1] - b[1], 2),
               "points_per_second": round((a[1] - b[1]) / (b[0] - a[0]), 3)}
              for a, b in zip(rows, rows[1:]) if a[1] - b[1] >= 5]
    cliffs.sort(key=lambda r: r["points_per_second"], reverse=True)
    middle = [r for r in rows if r[0] >= cutoff]
    slide = ((middle[0][1] - middle[-1][1]) / (middle[-1][0] - middle[0][0])) if len(middle) > 1 else None
    return {"samples": len(rows), "opening_at_seconds": cutoff, "opening_retention_percent": opening,
            "opening_drop_percentage_points": round(rows[0][1] - opening, 2) if opening is not None and rows[0][0] == 0 else None,
            "cliffs": cliffs[:5], "middle_loss_points_per_second": slide,
            "recommendation": ("Inspect the largest drop against your script: shorten setup or clarify the transition."
                               if cliffs else "Compare opening promise and payoff; inspect repeated explanation if the middle declines."),
            "note": "Diagnostic observations; retention alone cannot establish why viewers left. Values above 100% may reflect rewatching."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv")
    parser.add_argument("--axis", choices=["seconds", "percent"], default="seconds")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--retention-unit", choices=["percent", "fraction"], default="percent")
    args = parser.parse_args()
    try:
        report = analyze_csv(args.csv, axis=args.axis, duration=args.duration, retention_unit=args.retention_unit)
    except UnicodeError:
        parser.exit(2, "Invalid retention CSV: save the file as UTF-8.\n")
    except ValueError as exc:
        # Validation messages contain row/field information, never cell contents.
        parser.exit(2, f"Invalid retention CSV: {exc}\n")
    except OSError:
        parser.exit(2, "Cannot read retention CSV; check the path and file permissions.\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
