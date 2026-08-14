#!/usr/bin/env python3
"""Independent oracle for materials-l3-eos-transition.

Dependencies: Python 3.9+ standard library only.  Scientific truth is rebuilt
from energy_volume.csv and method_note.md; legacy_fit.py and
stale_transition.json are deliberately never read.  Submission code is never
imported or executed.  output/reproduce.py receives only static artifact checks;
an actual rerun belongs in a separately sandboxed CI/container stage.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any


TASK_ID = "materials-l3-eos-transition"
CSV_COLUMNS = ["phase", "V0_a3_atom", "E0_ev_atom", "B0_gpa"]
WEIGHTS = OrderedDict([
    ("phase_schema", 10),
    ("eos_parameters", 35),
    ("transition", 20),
    ("script", 10),
    ("report", 5),
])
TOLERANCES = {"V0": 0.05, "E0": 0.005, "B0": 1.0, "transition": 0.08}


class OracleError(Exception):
    """Official input/reference data is unusable."""


def finite(value: Any) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite numeric value")
    return parsed


def read_csv(path: Path, columns: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise ValueError(f"{path.name}: expected columns {columns}, got {reader.fieldnames}")
        return list(reader)


def solve_linear(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    n = len(rhs)
    work = [list(matrix[row]) + [rhs[row]] for row in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(work[row][column]))
        if abs(work[pivot][column]) < 1e-12:
            raise ValueError("singular quadratic fit")
        work[column], work[pivot] = work[pivot], work[column]
        divisor = work[column][column]
        work[column] = [value / divisor for value in work[column]]
        for row in range(n):
            if row == column:
                continue
            factor = work[row][column]
            work[row] = [left - factor * right for left, right in zip(work[row], work[column])]
    return [work[row][-1] for row in range(n)]


def quadratic_fit(points: list[tuple[float, float]]) -> dict[str, float]:
    design = [[1.0, volume, volume * volume] for volume, _ in points]
    values = [energy for _, energy in points]
    gram = [[sum(row[i] * row[j] for row in design) for j in range(3)] for i in range(3)]
    rhs = [sum(row[i] * value for row, value in zip(design, values)) for i in range(3)]
    c0, c1, a = solve_linear(gram, rhs)
    if a <= 0 or not all(math.isfinite(value) for value in (c0, c1, a)):
        raise ValueError("EOS curvature must be finite and positive")
    v0 = -c1 / (2.0 * a)
    e0 = c0 - c1 * c1 / (4.0 * a)
    return {"V0": v0, "E0": e0, "a": a}


def enthalpy(parameters: dict[str, float], pressure: float, conversion: float) -> float:
    # Analytic minimum of E0+a(V-V0)^2+(P/conversion)V.
    return (parameters["E0"] + pressure * parameters["V0"] / conversion
            - pressure * pressure / (4.0 * parameters["a"] * conversion * conversion))


def first_crossing(parameters: dict[str, dict[str, float]], conversion: float) -> dict[str, Any]:
    phases = list(parameters)
    if len(phases) != 2:
        raise ValueError("transition check requires exactly two phases")
    left, right = phases

    def difference(pressure: float) -> float:
        return enthalpy(parameters[left], pressure, conversion) - enthalpy(parameters[right], pressure, conversion)

    step = 0.001  # finer than the method-note maximum spacing of 0.01 GPa
    previous_p, previous_d = 0.0, difference(0.0)
    crossing = None
    for index in range(1, int(round(10.0 / step)) + 1):
        pressure = index * step
        current_d = difference(pressure)
        if previous_d == 0.0 or current_d == 0.0 or previous_d * current_d < 0.0:
            low, high = previous_p, pressure
            for _ in range(60):
                middle = (low + high) / 2.0
                if difference(low) * difference(middle) <= 0.0:
                    high = middle
                else:
                    low = middle
            crossing = (low + high) / 2.0
            break
        previous_p, previous_d = pressure, current_d
    if crossing is None:
        raise ValueError("no enthalpy crossing in 0-10 GPa")
    below_p = max(0.0, crossing - 1e-5)
    above_p = min(10.0, crossing + 1e-5)
    stable_below = left if difference(below_p) < 0 else right
    stable_above = left if difference(above_p) < 0 else right
    return {"pressure": crossing, "stable_below": stable_below, "stable_above": stable_above}


def load_truth(root: Path) -> dict[str, Any]:
    note = (root / "inputs" / "method_note.md").read_text(encoding="utf-8")
    constants = {finite(value) for value in re.findall(r"160\.217\d+", note)}
    if len(constants) != 1:
        raise OracleError("method note must define one pressure conversion constant")
    conversion = constants.pop()
    rows = read_csv(
        root / "inputs" / "energy_volume.csv",
        ["phase", "volume_cell_a3", "total_energy_ev", "n_atoms", "converged"],
    )
    grouped: OrderedDict[str, list[tuple[float, float]]] = OrderedDict()
    excluded = 0
    for row in rows:
        state = row["converged"].strip().lower()
        if state not in {"true", "false"}:
            raise OracleError(f"invalid converged flag: {row['converged']!r}")
        volume_cell = finite(row["volume_cell_a3"])
        total_energy = finite(row["total_energy_ev"])
        atoms = finite(row["n_atoms"])
        if atoms <= 0 or not atoms.is_integer():
            raise OracleError("n_atoms must be a positive integer")
        if state == "false":
            excluded += 1
            continue
        grouped.setdefault(row["phase"], []).append((volume_cell / atoms, total_energy / atoms))
    if set(grouped) != {"alpha", "beta"} or any(len(points) < 3 for points in grouped.values()):
        raise OracleError("official input needs alpha/beta and at least three converged points each")
    fitted: OrderedDict[str, dict[str, float]] = OrderedDict()
    for phase, points in grouped.items():
        fitted[phase] = quadratic_fit(points)
        fitted[phase]["B0"] = fitted[phase]["V0"] * 2.0 * fitted[phase]["a"] * conversion
    transition = first_crossing(fitted, conversion)
    return {"conversion": conversion, "parameters": fitted, "transition": transition,
            "excluded_nonconverged": excluded}


def inspect_eos(root: Path, truth: dict[str, Any]) -> dict[str, Any]:
    rows = read_csv(root / "output" / "eos_parameters.csv", CSV_COLUMNS)
    ids = [row["phase"] for row in rows]
    coverage = (len(ids) == len(set(ids)) == len(truth["parameters"])
                and set(ids) == set(truth["parameters"]))
    parsed: dict[str, dict[str, float]] = {}
    invalid_rows: list[str] = []
    for row in rows:
        try:
            values = {
                "V0": finite(row["V0_a3_atom"]),
                "E0": finite(row["E0_ev_atom"]),
                "B0": finite(row["B0_gpa"]),
            }
            if values["V0"] <= 0 or values["B0"] <= 0:
                raise ValueError("V0 and B0 must be positive")
            parsed[row["phase"]] = values
        except Exception:
            invalid_rows.append(row["phase"])
    comparisons: list[dict[str, Any]] = []
    for phase, expected in truth["parameters"].items():
        for key in ("V0", "E0", "B0"):
            actual = parsed.get(phase, {}).get(key)
            passed = actual is not None and abs(actual - expected[key]) <= TOLERANCES[key]
            comparisons.append({"phase": phase, "parameter": key, "actual": actual,
                                "expected": expected[key], "pass": passed})
    return {"coverage": coverage, "parsed": parsed, "invalid_rows": invalid_rows,
            "comparisons": comparisons}


def inspect_transition(root: Path, truth: dict[str, Any], submitted: dict[str, dict[str, float]]) -> dict[str, Any]:
    try:
        payload = json.loads((root / "output" / "transition.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("transition.json must contain an object")
        required = {"transition_pressure_gpa", "stable_below", "stable_above"}
        if not required.issubset(payload):
            raise ValueError(f"transition.json missing keys: {sorted(required - set(payload))}")
        pressure = finite(payload["transition_pressure_gpa"])
        pressure_ok = (0.0 <= pressure <= 10.0
                       and abs(pressure - truth["transition"]["pressure"]) <= TOLERANCES["transition"])
        direction_ok = (payload["stable_below"] == truth["transition"]["stable_below"]
                        and payload["stable_above"] == truth["transition"]["stable_above"])
        cross_ok = False
        submitted_crossing = None
        if set(submitted) == set(truth["parameters"]):
            reconstructed = {}
            for phase, values in submitted.items():
                a = values["B0"] / (2.0 * values["V0"] * truth["conversion"])
                if a <= 0:
                    raise ValueError("submitted EOS implies non-positive curvature")
                reconstructed[phase] = {"V0": values["V0"], "E0": values["E0"], "a": a}
            submitted_crossing = first_crossing(reconstructed, truth["conversion"])
            cross_ok = (abs(pressure - submitted_crossing["pressure"]) <= TOLERANCES["transition"]
                        and payload["stable_below"] == submitted_crossing["stable_below"]
                        and payload["stable_above"] == submitted_crossing["stable_above"])
        return {"valid": True, "pressure_ok": pressure_ok, "direction_ok": direction_ok,
                "cross_artifact_ok": cross_ok, "pressure": pressure,
                "submitted_crossing": submitted_crossing, "error": None}
    except Exception as exc:
        return {"valid": False, "pressure_ok": False, "direction_ok": False,
                "cross_artifact_ok": False, "pressure": None,
                "submitted_crossing": None, "error": str(exc)}


def script_check(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "output/reproduce.py is missing"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return False, f"output/reproduce.py is not UTF-8 text: {exc}"
    if not text.strip():
        return False, "output/reproduce.py is empty"
    try:
        tree = ast.parse(text, filename=path.name)
    except Exception as exc:
        return False, f"output/reproduce.py is not parseable Python: {exc}"
    stale_literals = [node.value for node in ast.walk(tree)
                      if isinstance(node, ast.Constant) and isinstance(node.value, str)
                      and "stale_transition" in node.value]
    if stale_literals:
        return False, "script references forbidden stale_transition input"
    return True, "non-empty UTF-8 Python with valid AST and no stale-result reference; not executed"


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
    return {"task_id": TASK_ID, "grader_status": "error", "hardgate_pass": False,
            "deterministic_score": 0, "criteria": zero_criteria(message),
            "hardgates": {}, "failure_codes": [code], "error": message}


def scored_failure(code: str, message: str) -> dict[str, Any]:
    return {"task_id": TASK_ID, "grader_status": "ok", "hardgate_pass": False,
            "deterministic_score": 0, "criteria": zero_criteria(message),
            "hardgates": {"core_artifacts_parseable": {"pass": False, "details": message}},
            "failure_codes": [code]}


def grade(root: Path) -> dict[str, Any]:
    try:
        truth = load_truth(root)
    except Exception as exc:
        return error_result("INPUT_REFERENCE_ERROR", str(exc))
    core = [root / "output" / "eos_parameters.csv", root / "output" / "transition.json"]
    missing = [str(path.relative_to(root)) for path in core if not path.is_file()]
    if missing:
        return scored_failure("CORE_ARTIFACT_MISSING", f"missing core artifacts: {missing}")
    try:
        eos = inspect_eos(root, truth)
    except Exception as exc:
        return scored_failure("CORE_ARTIFACT_INVALID", str(exc))
    transition = inspect_transition(root, truth, eos["parsed"])
    script_ok, script_detail = script_check(root / "output" / "reproduce.py")
    report_ok, report_detail = nonempty_utf8(root / "output" / "report.md")

    correct_parameters = sum(item["pass"] for item in eos["comparisons"])
    eos_earned = WEIGHTS["eos_parameters"] * correct_parameters / len(eos["comparisons"])
    transition_parts = [transition["pressure_ok"], transition["direction_ok"], transition["cross_artifact_ok"]]
    transition_earned = (10 if transition_parts[0] else 0) + (5 if transition_parts[1] else 0) + (5 if transition_parts[2] else 0)
    transition_detail = (f"pressure truth={truth['transition']['pressure']:.6f} GPa; "
                         f"expected direction={truth['transition']['stable_below']}→{truth['transition']['stable_above']}; "
                         f"cross-artifact consistency={transition['cross_artifact_ok']}")
    if transition["error"]:
        transition_detail += f"; invalid artifact: {transition['error']}"
    criteria = [
        criterion("phase_schema", 10 if eos["coverage"] and not eos["invalid_rows"] else 0,
                  eos["coverage"] and not eos["invalid_rows"],
                  f"exact alpha/beta coverage={eos['coverage']}; invalid rows={eos['invalid_rows']}"),
        criterion("eos_parameters", eos_earned, correct_parameters == len(eos["comparisons"]),
                  f"{correct_parameters}/{len(eos['comparisons'])} phase-parameter values within tolerances"),
        criterion("transition", transition_earned, all(transition_parts), transition_detail),
        criterion("script", 10 if script_ok else 0, script_ok,
                  script_detail + "; rerun deferred to isolated CI"),
        criterion("report", 5 if report_ok else 0, report_ok, report_detail),
    ]
    hardgates = {
        "normalized_converged_eos": {
            "pass": eos["coverage"] and not eos["invalid_rows"]
                    and correct_parameters == len(eos["comparisons"]),
            "details": "all converged points fitted per atom; non-converged input excluded by independent truth",
        },
        "first_transition_and_direction": {
            "pass": all(transition_parts),
            "details": "first 0-10 GPa crossing, direction, and EOS/transition consistency",
        },
        "required_artifacts_and_no_stale_result": {
            "pass": script_ok and report_ok,
            "details": "static script validity/no stale reference and non-empty report; submission code is not executed",
        },
    }
    code_map = {
        "normalized_converged_eos": "EOS_PARAMETER_MISMATCH",
        "first_transition_and_direction": "TRANSITION_MISMATCH",
        "required_artifacts_and_no_stale_result": "REQUIRED_ARTIFACT_INVALID_OR_STALE",
    }
    failures = [code_map[name] for name, gate in hardgates.items() if not gate["pass"]]
    return {
        "task_id": TASK_ID, "grader_status": "ok",
        "hardgate_pass": all(gate["pass"] for gate in hardgates.values()),
        "deterministic_score": round(sum(item["earned"] for item in criteria), 3),
        "criteria": criteria, "hardgates": hardgates, "failure_codes": failures,
        "reference": {
            "excluded_nonconverged_rows": truth["excluded_nonconverged"],
            "parameters": {phase: {key: round(values[key], 8) for key in ("V0", "E0", "B0")}
                           for phase, values in truth["parameters"].items()},
            "transition_pressure_gpa": round(truth["transition"]["pressure"], 8),
            "stable_below": truth["transition"]["stable_below"],
            "stable_above": truth["transition"]["stable_above"],
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
