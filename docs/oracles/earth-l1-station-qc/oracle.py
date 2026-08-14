#!/usr/bin/env python3
"""Deterministic artifact grader for earth-l1-station-qc.

The grader derives the expected QC result from the workspace inputs.  It does
not import or execute submission code.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


TASK_ID = "earth-l1-station-qc"
WEIGHTS = {
    "qc_flags": 30.0,
    "clean_row_set": 20.0,
    "value_ranges": 10.0,
    "qc_summary": 10.0,
    "report_exists": 10.0,
}


class OracleError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def criterion(name: str, earned: float, maximum: float, passed: bool, details: Any) -> dict[str, Any]:
    return {
        "name": name,
        "earned": round(max(0.0, min(maximum, earned)), 3),
        "max": maximum,
        "pass": bool(passed),
        "details": details,
    }


def zero_criteria(details: str) -> list[dict[str, Any]]:
    return [criterion(name, 0.0, maximum, False, details) for name, maximum in WEIGHTS.items()]


def regular_file(path: Path, *, core: bool = True) -> bool:
    ok = path.is_file() and not path.is_symlink()
    if core and not ok:
        raise OracleError("MISSING_ARTIFACT", f"missing regular file: {path}")
    return ok


def read_csv(path: Path, columns: list[str], *, trusted_input: bool = False) -> list[dict[str, str]]:
    if not path.is_file():
        code = "INPUT_ERROR" if trusted_input else "MISSING_ARTIFACT"
        raise OracleError(code, f"missing CSV: {path}")
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                raise OracleError(
                    "INVALID_ARTIFACT" if not trusted_input else "INPUT_ERROR",
                    f"{path.name}: expected columns {columns}, got {reader.fieldnames}",
                )
            rows = list(reader)
            if any(set(row) != set(columns) or any(not isinstance(row.get(key), str) for key in columns) for row in rows):
                raise OracleError(
                    "INPUT_ERROR" if trusted_input else "INVALID_ARTIFACT",
                    f"{path.name}: malformed row width or missing cell",
                )
    except OracleError:
        raise
    except Exception as exc:
        code = "INPUT_ERROR" if trusted_input else "INVALID_ARTIFACT"
        raise OracleError(code, f"cannot read {path.name}: {exc}") from exc
    return rows


def safe_read_csv(path: Path, columns: list[str]) -> tuple[list[dict[str, str]], str | None]:
    """Read an untrusted submission CSV without turning a bad artifact into a grader error."""
    try:
        return read_csv(path, columns), None
    except OracleError as exc:
        return [], str(exc)


def finite(text: str) -> float:
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not numeric: {text!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite number: {text!r}")
    return value


def derive_truth(inputs: Path) -> tuple[list[dict[str, str]], dict[str, str], list[dict[str, str]], dict[str, int], dict[str, Any]]:
    try:
        rules = json.loads((inputs / "qc_rules.json").read_text(encoding="utf-8"))
    except Exception as exc:
        raise OracleError("INPUT_ERROR", f"cannot read qc_rules.json: {exc}") from exc
    columns = ["row_id", "station_id", "timestamp_utc", "temp_c", "rh_pct", "precip_mm"]
    rows = read_csv(inputs / "station_observations.csv", columns, trusted_input=True)
    row_ids = [row["row_id"] for row in rows]
    if len(row_ids) != len(set(row_ids)):
        raise OracleError("INPUT_ERROR", "input row_id values are not unique")

    try:
        duplicate_key = list(rules["duplicate_key"])
        if rules["duplicate_policy"] != "keep the lowest row_id only":
            raise ValueError("unsupported duplicate policy")
        t_min, t_max = map(float, rules["valid_temperature_c"])
        rh_min, rh_max = map(float, rules["valid_relative_humidity_pct"])
        p_min = float(rules["minimum_precipitation_mm"])
        vocabulary = set(rules["reason_codes"])
    except Exception as exc:
        raise OracleError("INPUT_ERROR", f"invalid QC rules: {exc}") from exc

    groups: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in duplicate_key)].append(row)
    duplicate_ids: set[str] = set()
    for group in groups.values():
        duplicate_ids.update(row["row_id"] for row in sorted(group, key=lambda item: item["row_id"])[1:])

    reasons: dict[str, str] = {}
    for row in rows:
        row_id = row["row_id"]
        if row_id in duplicate_ids:
            reasons[row_id] = "DUPLICATE_TIMESTAMP"
            continue
        try:
            temp = finite(row["temp_c"])
            rh = finite(row["rh_pct"])
            precip = finite(row["precip_mm"])
        except ValueError as exc:
            raise OracleError("INPUT_ERROR", f"invalid input measurement at {row_id}: {exc}") from exc
        if not t_min <= temp <= t_max:
            reasons[row_id] = "TEMP_RANGE"
        elif not rh_min <= rh <= rh_max:
            reasons[row_id] = "RH_RANGE"
        elif precip < p_min:
            reasons[row_id] = "NEGATIVE_PRECIP"
    unknown = set(reasons.values()) - vocabulary
    if unknown:
        raise OracleError("INPUT_ERROR", f"derived reasons absent from vocabulary: {sorted(unknown)}")

    clean = [row for row in rows if row["row_id"] not in reasons]
    summary = {
        "input_rows": len(rows),
        "valid_rows": len(clean),
        "duplicate_rows": sum(reason == "DUPLICATE_TIMESTAMP" for reason in reasons.values()),
        "invalid_measurement_rows": sum(reason != "DUPLICATE_TIMESTAMP" for reason in reasons.values()),
    }
    return rows, reasons, clean, summary, {
        "temperature": (t_min, t_max),
        "humidity": (rh_min, rh_max),
        "precip_min": p_min,
    }


def grade(workspace: Path) -> dict[str, Any]:
    inputs, output = workspace / "inputs", workspace / "output"
    _, expected_reasons, expected_clean, expected_summary, limits = derive_truth(inputs)

    flag_rows, flag_error = safe_read_csv(output / "qc_flags.csv", ["row_id", "reason"])
    clean_rows, clean_error = safe_read_csv(
        output / "clean_observations.csv",
        ["row_id", "station_id", "timestamp_utc", "temp_c", "rh_pct", "precip_mm"],
    )
    summary_error = None
    submitted_summary: Any = {}
    summary_path = output / "qc_summary.json"
    if not regular_file(summary_path, core=False):
        summary_error = f"missing regular file: {summary_path}"
    else:
        try:
            submitted_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:
            summary_error = f"cannot read qc_summary.json: {exc}"

    # QC flags: compare (row_id, reason) as a set, while explicitly rejecting duplicates.
    expected_pairs = set(expected_reasons.items())
    actual_pairs = {(row["row_id"], row["reason"]) for row in flag_rows}
    flag_unique = len(flag_rows) == len(actual_pairs)
    correct_pairs = len(expected_pairs & actual_pairs)
    flag_denominator = max(len(expected_pairs), len(actual_pairs), 1)
    flags_pass = flag_error is None and flag_unique and actual_pairs == expected_pairs
    flags_earned = WEIGHTS["qc_flags"] * correct_pairs / flag_denominator
    if not flag_unique:
        flags_earned = 0.0

    expected_by_id = {row["row_id"]: row for row in expected_clean}
    actual_by_id = {row["row_id"]: row for row in clean_rows}
    clean_unique = len(clean_rows) == len(actual_by_id)
    exact_clean = 0
    for row_id, expected in expected_by_id.items():
        actual = actual_by_id.get(row_id)
        if not actual:
            continue
        try:
            exact = (
                actual["station_id"] == expected["station_id"]
                and actual["timestamp_utc"] == expected["timestamp_utc"]
                and abs(finite(actual["temp_c"]) - finite(expected["temp_c"])) <= 1e-9
                and abs(finite(actual["rh_pct"]) - finite(expected["rh_pct"])) <= 1e-9
                and abs(finite(actual["precip_mm"]) - finite(expected["precip_mm"])) <= 1e-9
            )
        except ValueError:
            exact = False
        exact_clean += bool(exact)
    clean_denominator = max(len(expected_by_id), len(actual_by_id), 1)
    clean_pass = clean_error is None and clean_unique and set(actual_by_id) == set(expected_by_id) and exact_clean == len(expected_by_id)
    clean_earned = WEIGHTS["clean_row_set"] * exact_clean / clean_denominator
    if not clean_unique:
        clean_earned = 0.0

    in_range = 0
    for row in clean_rows:
        try:
            valid = (
                limits["temperature"][0] <= finite(row["temp_c"]) <= limits["temperature"][1]
                and limits["humidity"][0] <= finite(row["rh_pct"]) <= limits["humidity"][1]
                and finite(row["precip_mm"]) >= limits["precip_min"]
            )
        except ValueError:
            valid = False
        in_range += bool(valid)
    ranges_pass = clean_error is None and bool(clean_rows) and clean_unique and in_range == len(clean_rows)
    ranges_earned = WEIGHTS["value_ranges"] * in_range / max(len(clean_rows), 1)
    if not clean_unique:
        ranges_earned = 0.0

    summary_schema = isinstance(submitted_summary, dict) and set(submitted_summary) == set(expected_summary)
    summary_matches = []
    for key, expected in expected_summary.items():
        value = submitted_summary.get(key) if isinstance(submitted_summary, dict) else None
        summary_matches.append(type(value) is int and value == expected)
    submitted_artifact_summary = {
        "input_rows": expected_summary["input_rows"],
        "valid_rows": len(clean_rows),
        "duplicate_rows": sum(row.get("reason") == "DUPLICATE_TIMESTAMP" for row in flag_rows),
        "invalid_measurement_rows": sum(row.get("reason") != "DUPLICATE_TIMESTAMP" for row in flag_rows),
    }
    cross_matches = []
    for key, expected in submitted_artifact_summary.items():
        value = submitted_summary.get(key) if isinstance(submitted_summary, dict) else None
        cross_matches.append(type(value) is int and value == expected)
    summary_pass = summary_error is None and summary_schema and all(summary_matches) and all(cross_matches)
    summary_earned = WEIGHTS["qc_summary"] * sum(
        truth and cross for truth, cross in zip(summary_matches, cross_matches)
    ) / len(summary_matches)
    if not summary_schema:
        summary_earned = 0.0

    report_path = output / "report.md"
    report_pass = regular_file(report_path, core=False) and report_path.stat().st_size > 0
    criteria = [
        criterion("qc_flags", flags_earned, 30.0, flags_pass, {
            "expected": sorted(expected_pairs), "actual": sorted(actual_pairs), "unique": flag_unique,
            "artifact_error": flag_error,
        }),
        criterion("clean_row_set", clean_earned, 20.0, clean_pass, {
            "expected_ids": sorted(expected_by_id), "actual_ids": sorted(actual_by_id),
            "exact_rows": exact_clean, "unique": clean_unique,
            "artifact_error": clean_error,
        }),
        criterion("value_ranges", ranges_earned, 10.0, ranges_pass, {
            "valid_rows": in_range, "submitted_rows": len(clean_rows), "all_values_must_be_finite": True,
        }),
        criterion("qc_summary", summary_earned, 10.0, summary_pass, {
            "expected": expected_summary, "actual": submitted_summary,
            "recomputed_from_submitted_csv_artifacts": submitted_artifact_summary,
            "per_field_truth_match": dict(zip(expected_summary, summary_matches)),
            "per_field_cross_artifact_match": dict(zip(expected_summary, cross_matches)),
            "artifact_error": summary_error,
        }),
        criterion("report_exists", 10.0 if report_pass else 0.0, 10.0, report_pass, {
            "path": "output/report.md", "nonempty": report_pass,
        }),
    ]
    hard_gates = {
        "all_and_only_bad_rows_flagged": flags_pass,
        "clean_table_correct": clean_pass and ranges_pass,
        "required_artifacts": summary_pass and report_pass,
    }
    failure_codes = []
    if not flags_pass:
        failure_codes.append("QC_FLAG_SET_MISMATCH")
    if not clean_pass:
        failure_codes.append("CLEAN_TABLE_MISMATCH")
    if not ranges_pass:
        failure_codes.append("INVALID_OR_NONFINITE_MEASUREMENT")
    if not summary_pass:
        failure_codes.append("QC_SUMMARY_MISMATCH")
    if not report_pass:
        failure_codes.append("MISSING_REPORT")
    return {
        "task_id": TASK_ID,
        "grader_status": "ok",
        "hardgate_pass": all(hard_gates.values()),
        "deterministic_score": round(sum(item["earned"] for item in criteria), 3),
        "criteria": criteria,
        "hard_gates": hard_gates,
        "failure_codes": failure_codes,
    }


def error_result(code: str, message: str) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "grader_status": "error",
        "hardgate_pass": False,
        "deterministic_score": 0.0,
        "criteria": zero_criteria(message),
        "hard_gates": {},
        "failure_codes": [code],
        "error": message,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        payload = grade(args.workspace.resolve())
    except OracleError as exc:
        payload = error_result(exc.code, str(exc))
    except Exception as exc:  # A grader bug should still produce the promised JSON contract.
        payload = error_result("ORACLE_INTERNAL_ERROR", f"unexpected grader error: {type(exc).__name__}: {exc}")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["grader_status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
