#!/usr/bin/env python3
"""Independent oracle for materials-l2-xrd-phase-mixture.

Dependencies: Python 3.9+ standard library only.  Scientific truth (peak
matches and non-negative mixture coefficients) is reconstructed from inputs.
Submission code is never imported or executed.  The script artifact is checked
only for existence, UTF-8 text, non-emptiness, and Python AST parseability;
actual reruns belong in a separately sandboxed CI/container stage.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import re
import struct
from collections import OrderedDict
from itertools import combinations
from pathlib import Path
from typing import Any


TASK_ID = "materials-l2-xrd-phase-mixture"
WEIGHTS = OrderedDict([
    ("fraction_contract", 15),
    ("fraction_range_phase_presence", 25),
    ("peak_assignments", 25),
    ("plot", 5),
    ("script", 5),
    ("report", 5),
])


class OracleError(Exception):
    """Expected grading error that should be rendered as JSON."""


def finite(value: Any) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite number")
    return parsed


def read_csv(path: Path, columns: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise ValueError(f"{path.name}: expected columns {columns}, got {reader.fieldnames}")
        return list(reader)


def solve_linear(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    n = len(rhs)
    augmented = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("singular least-squares system")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [a - factor * b for a, b in zip(augmented[row], augmented[column])]
    return [augmented[i][-1] for i in range(n)]


def least_squares(design: list[list[float]], values: list[float], columns: tuple[int, ...]) -> list[float]:
    gram = [[sum(row[i] * row[j] for row in design) for j in columns] for i in columns]
    rhs = [sum(row[i] * value for row, value in zip(design, values)) for i in columns]
    return solve_linear(gram, rhs)


def nnls_small(design: list[list[float]], values: list[float], n_columns: int) -> list[float]:
    """Enumerate active sets; sufficient and deterministic for three phases."""
    best_coefficients = [0.0] * n_columns
    best_error = sum(value * value for value in values)
    for size in range(1, n_columns + 1):
        for active in combinations(range(n_columns), size):
            try:
                fit = least_squares(design, values, active)
            except ValueError:
                continue
            if any(value < -1e-10 for value in fit):
                continue
            coefficients = [0.0] * n_columns
            for index, value in zip(active, fit):
                coefficients[index] = max(0.0, value)
            error = sum((observed - sum(row[j] * coefficients[j] for j in range(n_columns))) ** 2
                        for row, observed in zip(design, values))
            if error < best_error:
                best_error, best_coefficients = error, coefficients
    return best_coefficients


def load_truth(root: Path) -> dict[str, Any]:
    note = (root / "inputs" / "measurement_note.md").read_text(encoding="utf-8")
    tolerance_match = re.search(r"±\s*([0-9.]+)\s*°", note)
    noise_match = re.search(r"below intensity\s*`?([0-9.]+)`?", note, re.IGNORECASE)
    if not tolerance_match or not noise_match:
        raise OracleError("measurement note does not define matching tolerance and noise threshold")
    tolerance = float(tolerance_match.group(1))
    noise_threshold = float(noise_match.group(1))
    observed_rows = read_csv(root / "inputs" / "observed_peaks.csv",
                             ["peak_id", "two_theta_deg", "intensity"])
    reference_rows = read_csv(root / "inputs" / "reference_patterns.csv",
                              ["phase", "two_theta_deg", "relative_intensity"])
    observed_ids = [row["peak_id"] for row in observed_rows]
    if len(observed_ids) != len(set(observed_ids)):
        raise OracleError("duplicate peak IDs in input")
    phases = list(dict.fromkeys(row["phase"] for row in reference_rows))
    references: dict[str, list[tuple[float, float]]] = {phase: [] for phase in phases}
    for row in reference_rows:
        references[row["phase"]].append((finite(row["two_theta_deg"]), finite(row["relative_intensity"])))

    assignments: dict[str, str] = {}
    design: list[list[float]] = []
    values: list[float] = []
    for row in observed_rows:
        peak_id = row["peak_id"]
        theta, intensity = finite(row["two_theta_deg"]), finite(row["intensity"])
        if intensity < noise_threshold:
            assignments[peak_id] = "noise"
            continue
        matched: list[str] = []
        pattern_row: list[float] = []
        for phase in phases:
            candidates = [(abs(theta - position), rel) for position, rel in references[phase]
                          if abs(theta - position) <= tolerance]
            if candidates:
                matched.append(phase)
                pattern_row.append(min(candidates)[1])
            else:
                pattern_row.append(0.0)
        assignments[peak_id] = "+".join(matched) if matched else "noise"
        if matched:
            design.append(pattern_row)
            values.append(intensity)
    coefficients = nnls_small(design, values, len(phases))
    total = sum(coefficients)
    if total <= 0:
        raise OracleError("could not fit any supported reference phase")
    fractions = {phase: coefficients[i] / total for i, phase in enumerate(phases)}
    return {
        "phases": phases, "peak_ids": observed_ids, "assignments": assignments,
        "fractions": fractions, "tolerance": tolerance,
        "noise_threshold": noise_threshold,
    }


def inspect_core(root: Path, truth: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    out = root / "output"
    fraction_rows = read_csv(out / "phase_fractions.csv", ["phase", "fraction"])
    fraction_ids = [row["phase"] for row in fraction_rows]
    parsed: dict[str, float] = {}
    numeric_valid = True
    for row in fraction_rows:
        try:
            parsed[row["phase"]] = finite(row["fraction"])
        except Exception:
            numeric_valid = False
    fraction_contract = (numeric_valid and len(fraction_ids) == len(set(fraction_ids)) == len(truth["phases"])
                         and set(fraction_ids) == set(truth["phases"])
                         and all(value >= 0 for value in parsed.values())
                         and abs(sum(parsed.values()) - 1.0) <= 1e-6)
    fraction_science = False
    if fraction_contract:
        fraction_science = all(
            abs(parsed[phase] - truth["fractions"][phase]) <= (0.03 if truth["fractions"][phase] < 1e-8 else 0.05)
            for phase in truth["phases"]
        )

    assignment_rows = read_csv(out / "peak_assignments.csv", ["peak_id", "assignment"])
    assignment_ids = [row["peak_id"] for row in assignment_rows]
    assignment_map = {row["peak_id"]: row["assignment"].strip() for row in assignment_rows}
    assignment_coverage = (len(assignment_ids) == len(set(assignment_ids)) == len(truth["peak_ids"])
                           and set(assignment_ids) == set(truth["peak_ids"]))
    correct = sum(assignment_map.get(peak_id) == expected
                  for peak_id, expected in truth["assignments"].items())
    checks = {
        "fraction_contract": fraction_contract,
        "fraction_science": fraction_science,
        "parsed_fractions": parsed,
        "assignment_coverage": assignment_coverage,
        "assignment_correct": correct,
        "assignment_total": len(truth["assignments"]),
    }
    details = {
        "fraction_contract": "all reference phases exactly once; finite non-negative fractions; sum=1±1e-6",
        "fraction_science": "input-derived expected fractions: " + ", ".join(
            f"{phase}={truth['fractions'][phase]:.5f}" for phase in truth["phases"]
        ),
        "assignments": f"{correct}/{len(truth['assignments'])} exact input-derived assignments; coverage={assignment_coverage}",
    }
    return checks, details


def inspect_png(path: Path) -> tuple[bool, str]:
    try:
        data = path.read_bytes()
        if len(data) < 1024 or data[:8] != b"\x89PNG\r\n\x1a\n":
            return False, "not a non-trivial PNG"
        if data[12:16] != b"IHDR" or len(data) < 33:
            return False, "PNG lacks a valid IHDR"
        width, height = struct.unpack(">II", data[16:24])
        if width < 320 or height < 240 or b"IEND" not in data[-32:]:
            return False, f"PNG dimensions/end marker invalid ({width}x{height})"
        return True, f"valid non-trivial PNG ({width}x{height}, {len(data)} bytes)"
    except Exception as exc:
        return False, f"PNG inspection failed: {exc}"


def script_check(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"{path.name} is missing"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return False, f"script is not UTF-8 text: {exc}"
    if not text.strip():
        return False, "script is empty"
    try:
        ast.parse(text, filename=path.name)
    except Exception as exc:
        return False, f"script is not parseable Python: {exc}"
    return True, "non-empty UTF-8 Python with valid AST; not executed (rerun deferred to isolated CI)"


def nonempty_utf8(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"{path.name} is missing"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return False, f"{path.name} is not UTF-8 text: {exc}"
    if not text.strip():
        return False, f"{path.name} is empty"
    return True, f"non-empty UTF-8 {path.name}"


def criterion(name: str, earned: float, passed: bool, details: str) -> dict[str, Any]:
    return {"id": name, "earned": round(max(0.0, min(float(earned), WEIGHTS[name])), 3),
            "max": WEIGHTS[name], "pass": bool(passed), "details": details}


def zero_criteria(details: str) -> list[dict[str, Any]]:
    return [criterion(name, 0, False, details) for name in WEIGHTS]


def error_result(code: str, message: str) -> dict[str, Any]:
    return {
        "task_id": TASK_ID, "grader_status": "error", "hardgate_pass": False,
        "deterministic_score": 0, "criteria": zero_criteria(message),
        "hardgates": {}, "failure_codes": [code], "error": message,
    }


def scored_failure(code: str, message: str) -> dict[str, Any]:
    return {
        "task_id": TASK_ID, "grader_status": "ok", "hardgate_pass": False,
        "deterministic_score": 0, "criteria": zero_criteria(message),
        "hardgates": {}, "failure_codes": [code],
    }


def grade(root: Path) -> dict[str, Any]:
    try:
        truth = load_truth(root)
    except Exception as exc:
        return error_result("INPUT_REFERENCE_ERROR", str(exc))
    core = [root / "output" / "phase_fractions.csv", root / "output" / "peak_assignments.csv"]
    missing = [str(path.relative_to(root)) for path in core if not path.is_file()]
    if missing:
        return scored_failure("CORE_ARTIFACT_MISSING", f"missing core artifacts: {missing}")
    try:
        checks, details = inspect_core(root, truth)
    except Exception as exc:
        return scored_failure("CORE_ARTIFACT_INVALID", str(exc))

    plot_ok, plot_detail = inspect_png(root / "output" / "fit_plot.png")
    script_ok, script_detail = script_check(root / "output" / "analyze.py")
    report_ok, report_detail = nonempty_utf8(root / "output" / "report.md")
    assignment_earned = WEIGHTS["peak_assignments"] * checks["assignment_correct"] / checks["assignment_total"]
    if not checks["assignment_coverage"]:
        assignment_earned = 0.0
    criteria = [
        criterion("fraction_contract", 15 if checks["fraction_contract"] else 0,
                  checks["fraction_contract"], details["fraction_contract"]),
        criterion("fraction_range_phase_presence", 25 if checks["fraction_science"] else 0,
                  checks["fraction_science"], details["fraction_science"]),
        criterion("peak_assignments", assignment_earned,
                  checks["assignment_coverage"] and checks["assignment_correct"] == checks["assignment_total"],
                  details["assignments"]),
        criterion("plot", 5 if plot_ok else 0, plot_ok, plot_detail),
        criterion("script", 5 if script_ok else 0, script_ok, script_detail),
        criterion("report", 5 if report_ok else 0, report_ok, report_detail),
    ]

    hardgates = {
        "fractions_physical_complete_and_supported": {
            "pass": checks["fraction_contract"] and checks["fraction_science"],
            "details": "all phases included; non-negative normalized fractions; gamma decoy insignificant",
        },
        "peak_identity_and_shared_peaks": {
            "pass": checks["assignment_coverage"] and checks["assignment_correct"] == checks["assignment_total"],
            "details": "every observed peak exactly once; shared alpha+beta and noise handled",
        },
        "required_artifacts": {
            "pass": plot_ok and script_ok and report_ok,
            "details": "valid fit PNG, statically valid analyze.py, and non-empty report.md; rerun deferred to isolated CI",
        },
    }
    code_map = {
        "fractions_physical_complete_and_supported": "PHASE_FRACTION_INVALID",
        "peak_identity_and_shared_peaks": "PEAK_ASSIGNMENT_MISMATCH",
        "required_artifacts": "REQUIRED_ARTIFACT_INVALID",
    }
    failures = [code_map[name] for name, gate in hardgates.items() if not gate["pass"]]
    return {
        "task_id": TASK_ID, "grader_status": "ok",
        "hardgate_pass": all(gate["pass"] for gate in hardgates.values()),
        "deterministic_score": round(sum(item["earned"] for item in criteria), 3),
        "criteria": criteria, "hardgates": hardgates, "failure_codes": failures,
        "reference": {
            "match_tolerance_deg": truth["tolerance"], "noise_threshold": truth["noise_threshold"],
            "fractions": {key: round(value, 8) for key, value in truth["fractions"].items()},
            "assignments": truth["assignments"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        root = args.workspace.resolve(strict=True)
        result = grade(root)
    except Exception as exc:
        result = error_result("WORKSPACE_ERROR", str(exc))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(payload, encoding="utf-8")
        except Exception as exc:
            result.setdefault("failure_codes", []).append("OUT_WRITE_ERROR")
            result["out_error"] = str(exc)
            payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(payload, end="")
    return 0 if result["grader_status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
