#!/usr/bin/env python3
"""Deterministic artifact grader for earth-l2-burn-severity."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


TASK_ID = "earth-l2-burn-severity"
WEIGHTS = {
    "cell_region_coverage": 5.0,
    "dnbr": 30.0,
    "severity": 15.0,
    "cloud_mask": 10.0,
    "region_summary": 10.0,
    "analysis_script_exists": 5.0,
    "report_exists": 5.0,
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
        raise OracleError("INPUT_ERROR" if trusted_input else "MISSING_ARTIFACT", f"missing CSV: {path}")
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                raise OracleError(
                    "INPUT_ERROR" if trusted_input else "INVALID_ARTIFACT",
                    f"{path.name}: expected columns {columns}, got {reader.fieldnames}",
                )
            rows = list(reader)
            if any(set(row) != set(columns) or any(not isinstance(row.get(key), str) for key in columns) for row in rows):
                raise OracleError(
                    "INPUT_ERROR" if trusted_input else "INVALID_ARTIFACT",
                    f"{path.name}: malformed row width or missing cell",
                )
            return rows
    except OracleError:
        raise
    except Exception as exc:
        raise OracleError(
            "INPUT_ERROR" if trusted_input else "INVALID_ARTIFACT",
            f"cannot read {path.name}: {exc}",
        ) from exc


def safe_read_csv(path: Path, columns: list[str]) -> tuple[list[dict[str, str]], str | None]:
    try:
        return read_csv(path, columns), None
    except OracleError as exc:
        return [], str(exc)


def python_script_status(path: Path) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {
        "path": str(path),
        "executed_by_oracle": False,
        "rerun_policy": "Execute only in an isolated CI/container; this oracle never executes submission code.",
    }
    if not regular_file(path, core=False):
        details["error"] = "missing, non-regular, or symlink"
        return False, details
    try:
        source = path.read_text(encoding="utf-8")
        if not source.strip():
            raise ValueError("empty script")
        ast.parse(source, filename=path.name)
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        details["error"] = f"not nonempty UTF-8 parseable Python: {exc}"
        return False, details
    details["utf8_nonempty_ast_parseable"] = True
    return True, details


def finite(text: str) -> float:
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not numeric: {text!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite number: {text!r}")
    return value


def close(actual: float, expected: float, atol: float = 1e-6) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= atol


def parse_bool(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"invalid boolean: {text!r}")
    return normalized == "true"


def classify(value: float, classes: list[dict[str, Any]]) -> str:
    for spec in classes:
        lower = spec.get("minimum")
        upper = spec.get("maximum_exclusive")
        if (lower is None or value >= float(lower)) and (upper is None or value < float(upper)):
            return str(spec["name"])
    raise ValueError(f"no severity class covers dNBR={value}")


def derive_truth(inputs: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    columns = ["cell_id", "region", "pre_nir", "pre_swir2", "post_nir", "post_swir2", "cloud_pre", "cloud_post"]
    rows = read_csv(inputs / "burn_pixels.csv", columns, trusted_input=True)
    try:
        config = json.loads((inputs / "classification.json").read_text(encoding="utf-8"))
        classes = list(config["classes"])
        class_names = [str(item["name"]) for item in classes]
        if len(classes) == 0 or len(class_names) != len(set(class_names)):
            raise ValueError("severity class names must be nonempty and unique")
    except Exception as exc:
        raise OracleError("INPUT_ERROR", f"cannot parse classification.json: {exc}") from exc

    expected: dict[str, dict[str, Any]] = {}
    for row in rows:
        cell_id = row["cell_id"]
        if not cell_id or cell_id in expected:
            raise OracleError("INPUT_ERROR", f"duplicate or blank input cell_id: {cell_id!r}")
        try:
            pre_nir, pre_swir = finite(row["pre_nir"]), finite(row["pre_swir2"])
            post_nir, post_swir = finite(row["post_nir"]), finite(row["post_swir2"])
            masked = (
                parse_bool(row["cloud_pre"])
                or parse_bool(row["cloud_post"])
                or pre_nir + pre_swir == 0.0
                or post_nir + post_swir == 0.0
            )
        except ValueError as exc:
            raise OracleError("INPUT_ERROR", f"invalid input row {cell_id}: {exc}") from exc
        if masked:
            expected[cell_id] = {"region": row["region"], "dnbr": None, "severity": None, "status": "masked"}
            continue
        pre_nbr = (pre_nir - pre_swir) / (pre_nir + pre_swir)
        post_nbr = (post_nir - post_swir) / (post_nir + post_swir)
        dnbr = pre_nbr - post_nbr
        expected[cell_id] = {
            "region": row["region"], "dnbr": dnbr, "severity": classify(dnbr, classes), "status": "valid",
        }

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in expected.values():
        if item["status"] == "valid":
            grouped[item["region"]].append(item)
    summaries: dict[str, dict[str, Any]] = {}
    for region in sorted({item["region"] for item in expected.values()}):
        valid = grouped[region]
        summaries[region] = {
            "region": region,
            "valid_cells": len(valid),
            **{name: sum(item["severity"] == name for item in valid) for name in class_names},
            "mean_dnbr": mean(item["dnbr"] for item in valid),
        }
    return expected, summaries, class_names


def summary_from_submission(
    by_cell: dict[str, dict[str, str]], expected_ids: set[str], class_names: list[str]
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for cell_id in expected_ids:
        row = by_cell.get(cell_id)
        if not row or row.get("status") != "valid":
            continue
        try:
            value = finite(row["dnbr"])
        except ValueError:
            continue
        if row.get("severity") not in class_names:
            continue
        grouped[row["region"]].append((value, row["severity"]))
    result: dict[str, dict[str, Any]] = {}
    for region, values in grouped.items():
        result[region] = {
            "region": region,
            "valid_cells": len(values),
            **{name: sum(label == name for _, label in values) for name in class_names},
            "mean_dnbr": mean(value for value, _ in values),
        }
    return result


def summary_row_matches(actual: dict[str, str] | None, expected: dict[str, Any], class_names: list[str]) -> bool:
    if not actual:
        return False
    try:
        return (
            actual["region"] == expected["region"]
            and int(actual["valid_cells"]) == expected["valid_cells"]
            and all(int(actual[name]) == expected[name] for name in class_names)
            and close(finite(actual["mean_dnbr"]), expected["mean_dnbr"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def grade(workspace: Path) -> dict[str, Any]:
    inputs, output = workspace / "inputs", workspace / "output"
    expected, expected_summary, class_names = derive_truth(inputs)
    pixel_columns = ["cell_id", "region", "dnbr", "severity", "status"]
    pixel_rows, pixel_error = safe_read_csv(output / "burn_pixels.csv", pixel_columns)
    summary_columns = ["region", "valid_cells", *class_names, "mean_dnbr"]
    summary_rows, summary_error = safe_read_csv(output / "region_summary.csv", summary_columns)

    by_cell = {row["cell_id"]: row for row in pixel_rows}
    unique_cells = len(pixel_rows) == len(by_cell)
    expected_ids, actual_ids = set(expected), set(by_cell)
    coverage_matches = sum(
        cell_id in by_cell and by_cell[cell_id].get("region") == item["region"]
        for cell_id, item in expected.items()
    )
    coverage_denominator = max(len(expected_ids), len(actual_ids), 1)
    coverage_pass = pixel_error is None and unique_cells and actual_ids == expected_ids and coverage_matches == len(expected)
    coverage_earned = 5.0 * coverage_matches / coverage_denominator
    if not unique_cells:
        coverage_earned = 0.0

    valid_ids = [cell_id for cell_id, item in expected.items() if item["status"] == "valid"]
    masked_ids = [cell_id for cell_id, item in expected.items() if item["status"] == "masked"]
    dnbr_correct = severity_correct = mask_correct = 0
    for cell_id in valid_ids:
        row, truth = by_cell.get(cell_id, {}), expected[cell_id]
        try:
            dnbr_correct += row.get("region") == truth["region"] and close(finite(row["dnbr"]), truth["dnbr"])
        except ValueError:
            pass
        severity_correct += row.get("severity") == truth["severity"] and row.get("status") == "valid"
    for cell_id in masked_ids:
        row = by_cell.get(cell_id, {})
        mask_correct += (
            row.get("region") == expected[cell_id]["region"]
            and row.get("status") == "masked"
            and row.get("dnbr") == ""
            and row.get("severity") == ""
        )
    dnbr_pass = coverage_pass and dnbr_correct == len(valid_ids)
    severity_pass = coverage_pass and severity_correct == len(valid_ids)
    mask_pass = coverage_pass and mask_correct == len(masked_ids)

    summary_by_region = {row["region"]: row for row in summary_rows}
    unique_regions = len(summary_rows) == len(summary_by_region)
    submitted_derived = summary_from_submission(by_cell, expected_ids, class_names)
    summary_correct = 0
    summary_cross_consistent = 0
    for region, truth in expected_summary.items():
        actual = summary_by_region.get(region)
        summary_correct += summary_row_matches(actual, truth, class_names)
        derived = submitted_derived.get(region)
        summary_cross_consistent += bool(derived) and summary_row_matches(actual, derived, class_names)
    summary_pass = (
        summary_error is None
        and unique_regions
        and set(summary_by_region) == set(expected_summary)
        and summary_correct == len(expected_summary)
        and summary_cross_consistent == len(expected_summary)
    )
    summary_earned = 10.0 * sum(
        summary_row_matches(summary_by_region.get(region), truth, class_names)
        and summary_row_matches(summary_by_region.get(region), submitted_derived.get(region, {}), class_names)
        for region, truth in expected_summary.items()
    ) / max(len(expected_summary), 1)
    if not unique_regions:
        summary_earned = 0.0

    script_path, report_path = output / "analyze.py", output / "report.md"
    script_pass, script_details = python_script_status(script_path)
    report_pass = regular_file(report_path, core=False) and report_path.stat().st_size > 0
    criteria = [
        criterion("cell_region_coverage", coverage_earned, 5.0, coverage_pass, {
            "expected_ids": sorted(expected_ids), "actual_ids": sorted(actual_ids),
            "correct_cell_region_pairs": coverage_matches, "unique": unique_cells,
            "artifact_error": pixel_error,
        }),
        criterion("dnbr", 30.0 * dnbr_correct / max(len(valid_ids), 1), 30.0, dnbr_pass, {
            "correct": dnbr_correct, "expected_valid": len(valid_ids), "absolute_tolerance": 1e-6,
        }),
        criterion("severity", 15.0 * severity_correct / max(len(valid_ids), 1), 15.0, severity_pass, {
            "correct": severity_correct, "expected_valid": len(valid_ids), "class_order": class_names,
        }),
        criterion("cloud_mask", 10.0 * mask_correct / max(len(masked_ids), 1), 10.0, mask_pass, {
            "correct": mask_correct, "masked_cell_ids": masked_ids,
        }),
        criterion("region_summary", summary_earned, 10.0, summary_pass, {
            "expected": expected_summary, "correct_truth_rows": summary_correct,
            "cross_artifact_consistent_rows": summary_cross_consistent,
            "artifact_error": summary_error,
        }),
        criterion("analysis_script_exists", 5.0 if script_pass else 0.0, 5.0, script_pass, script_details),
        criterion("report_exists", 5.0 if report_pass else 0.0, 5.0, report_pass, {
            "path": "output/report.md", "nonempty": report_pass,
        }),
    ]
    hard_gates = {
        "cell_set_complete": coverage_pass,
        "dnbr_and_classification": dnbr_pass and severity_pass,
        "cloud_mask_respected": mask_pass,
        "summary_correct": summary_pass,
        "required_artifacts": script_pass and report_pass,
    }
    failure_codes = []
    for passed, code in [
        (coverage_pass, "CELL_REGION_SET_MISMATCH"),
        (dnbr_pass, "DNBR_MISMATCH"),
        (severity_pass, "SEVERITY_MISMATCH"),
        (mask_pass, "MASK_VIOLATION"),
        (summary_pass, "REGION_SUMMARY_MISMATCH"),
        (script_pass, "MISSING_ANALYSIS_SCRIPT"),
        (report_pass, "MISSING_REPORT"),
    ]:
        if not passed:
            failure_codes.append(code)
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
    except Exception as exc:
        payload = error_result("ORACLE_INTERNAL_ERROR", f"unexpected grader error: {type(exc).__name__}: {exc}")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["grader_status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
