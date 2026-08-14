#!/usr/bin/env python3
"""Deterministic artifact grader for earth-l3-rainfall-runoff."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


TASK_ID = "earth-l3-rainfall-runoff"
PARAMETER_KEYS = ["capacity_mm", "recession_day", "et_factor"]
METRIC_KEYS = ["calibration_nse", "validation_nse", "validation_kge"]
BOUNDS = {
    "capacity_mm": (25.0, 70.0),
    "recession_day": (0.02, 0.15),
    "et_factor": (0.3, 1.1),
}
WEIGHTS = {
    "parameter_bounds": 5.0,
    "date_and_period": 10.0,
    "daily_values": 15.0,
    "calibration_validation_performance": 25.0,
    "metrics_consistency": 10.0,
    "calibration_script_exists": 10.0,
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


def finite(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric result")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not numeric: {value!r}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite number: {value!r}")
    return parsed


def close(actual: float, expected: float, atol: float) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= atol


def simulate(source: list[dict[str, str]], parameters: dict[str, float]) -> list[float]:
    storage = 18.0
    flows: list[float] = []
    for row in source:
        precip, pet = finite(row["precip_mm"]), finite(row["pet_mm"])
        available = max(0.0, precip - parameters["et_factor"] * pet)
        pre_storage = storage + available
        quickflow = max(0.0, pre_storage - parameters["capacity_mm"])
        storage = min(parameters["capacity_mm"], pre_storage)
        baseflow = parameters["recession_day"] * storage
        storage -= baseflow
        flows.append(quickflow + baseflow)
    return flows


def nse(observed: list[float], simulated: list[float]) -> float:
    center = mean(observed)
    denominator = sum((value - center) ** 2 for value in observed)
    if denominator == 0.0:
        raise ValueError("NSE is undefined for constant observations")
    return 1.0 - sum((obs - sim) ** 2 for obs, sim in zip(observed, simulated)) / denominator


def kge(observed: list[float], simulated: list[float]) -> float:
    observed_mean, simulated_mean = mean(observed), mean(simulated)
    observed_sd, simulated_sd = pstdev(observed), pstdev(simulated)
    if observed_mean == 0.0 or observed_sd == 0.0:
        raise ValueError("KGE is undefined for zero-mean or constant observations")
    covariance = mean(
        (obs - observed_mean) * (sim - simulated_mean)
        for obs, sim in zip(observed, simulated)
    )
    correlation = covariance / (observed_sd * simulated_sd) if simulated_sd else 0.0
    variability_ratio = simulated_sd / observed_sd
    bias_ratio = simulated_mean / observed_mean
    return 1.0 - math.sqrt(
        (correlation - 1.0) ** 2 + (variability_ratio - 1.0) ** 2 + (bias_ratio - 1.0) ** 2
    )


def load_inputs(inputs: Path) -> list[dict[str, str]]:
    source = read_csv(inputs / "catchment.csv", ["date", "precip_mm", "pet_mm", "qobs_mm"], trusted_input=True)
    if len(source) != 70:
        raise OracleError("INPUT_ERROR", f"expected 70 catchment rows, got {len(source)}")
    dates = [row["date"] for row in source]
    if len(dates) != len(set(dates)):
        raise OracleError("INPUT_ERROR", "catchment dates are not unique")
    for index, row in enumerate(source, start=1):
        try:
            finite(row["precip_mm"])
            finite(row["pet_mm"])
            finite(row["qobs_mm"])
        except ValueError as exc:
            raise OracleError("INPUT_ERROR", f"invalid catchment row {index}: {exc}") from exc
    if not (inputs / "method_note.md").is_file():
        raise OracleError("INPUT_ERROR", "missing method_note.md")
    return source


def parse_json_object(path: Path) -> dict[str, Any]:
    regular_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise OracleError("INVALID_ARTIFACT", f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise OracleError("INVALID_ARTIFACT", f"{path.name} must contain one JSON object")
    return value


def safe_json_object(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        return parse_json_object(path), None
    except OracleError as exc:
        return {}, str(exc)


def grade(workspace: Path) -> dict[str, Any]:
    inputs, output = workspace / "inputs", workspace / "output"
    source = load_inputs(inputs)
    raw_parameters, parameter_error = safe_json_object(output / "parameters.json")
    parameters: dict[str, float] = {}
    parameter_value_valid: dict[str, bool] = {}
    for key in PARAMETER_KEYS:
        try:
            parameters[key] = finite(raw_parameters.get(key))
            parameter_value_valid[key] = True
        except ValueError:
            parameters[key] = math.nan
            parameter_value_valid[key] = False
    parameter_schema = set(raw_parameters) == set(PARAMETER_KEYS)
    individual_bounds = {
        key: parameter_value_valid[key] and BOUNDS[key][0] <= parameters[key] <= BOUNDS[key][1]
        for key in PARAMETER_KEYS
    }
    bounds_pass = parameter_error is None and parameter_schema and all(individual_bounds.values())

    simulation = simulate(source, parameters) if bounds_pass else [math.nan] * len(source)
    daily_rows, daily_error = safe_read_csv(
        output / "daily_simulation.csv",
        ["date", "observed_mm", "simulated_mm", "period"],
    )
    expected_periods = ["warmup"] * 7 + ["calibration"] * 38 + ["validation"] * 25
    submitted_dates = [row["date"] for row in daily_rows]
    date_unique = len(submitted_dates) == len(set(submitted_dates))
    date_matches = sum(
        index < len(daily_rows)
        and daily_rows[index]["date"] == source[index]["date"]
        and daily_rows[index]["period"] == expected_periods[index]
        for index in range(len(source))
    )
    date_period_pass = daily_error is None and date_unique and len(daily_rows) == len(source) and date_matches == len(source)
    date_period_earned = 10.0 * date_matches / max(len(source), len(daily_rows), 1)
    if not date_unique:
        date_period_earned = 0.0

    observed_correct = simulated_correct = 0
    for index, source_row in enumerate(source):
        if index >= len(daily_rows):
            continue
        submitted = daily_rows[index]
        try:
            observed_correct += close(finite(submitted["observed_mm"]), finite(source_row["qobs_mm"]), 1e-6)
            simulated_correct += bounds_pass and close(finite(submitted["simulated_mm"]), simulation[index], 1e-5)
        except ValueError:
            pass
    daily_ratio = (observed_correct + simulated_correct) / (2 * len(source))
    daily_pass = date_period_pass and observed_correct == simulated_correct == len(source)

    observed = [finite(row["qobs_mm"]) for row in source]
    if bounds_pass:
        calibration_nse = nse(observed[7:45], simulation[7:45])
        validation_nse = nse(observed[45:], simulation[45:])
        validation_kge = kge(observed[45:], simulation[45:])
    else:
        calibration_nse = validation_nse = validation_kge = -math.inf
    calibration_pass = math.isfinite(calibration_nse) and calibration_nse >= 0.98
    validation_pass = math.isfinite(validation_nse) and validation_nse >= 0.95
    performance_pass = bounds_pass and calibration_pass and validation_pass
    performance_earned = 12.5 * calibration_pass + 12.5 * validation_pass

    raw_metrics, metrics_error = safe_json_object(output / "metrics.json")
    metric_schema = set(raw_metrics) == set(METRIC_KEYS)
    recomputed_metrics = {
        "calibration_nse": calibration_nse,
        "validation_nse": validation_nse,
        "validation_kge": validation_kge,
    }
    submitted_daily_metrics: dict[str, float] | None = None
    if date_period_pass:
        try:
            submitted_simulation = [finite(row["simulated_mm"]) for row in daily_rows]
            submitted_daily_metrics = {
                "calibration_nse": nse(observed[7:45], submitted_simulation[7:45]),
                "validation_nse": nse(observed[45:], submitted_simulation[45:]),
                "validation_kge": kge(observed[45:], submitted_simulation[45:]),
            }
        except ValueError:
            submitted_daily_metrics = None
    metric_matches: dict[str, bool] = {}
    for key in METRIC_KEYS:
        try:
            reported = finite(raw_metrics.get(key))
            metric_matches[key] = (
                bounds_pass
                and submitted_daily_metrics is not None
                and close(reported, recomputed_metrics[key], 1e-5)
                and close(reported, submitted_daily_metrics[key], 1e-5)
            )
        except ValueError:
            metric_matches[key] = False
    metrics_pass = metrics_error is None and metric_schema and all(metric_matches.values())
    metrics_earned = 10.0 * sum(metric_matches.values()) / len(METRIC_KEYS)
    if not metric_schema:
        metrics_earned = 0.0

    script_path, report_path = output / "calibrate.py", output / "report.md"
    script_pass, script_details = python_script_status(script_path)
    report_pass = regular_file(report_path, core=False) and report_path.stat().st_size > 0
    criteria = [
        criterion("parameter_bounds", 5.0 * sum(individual_bounds.values()) / len(PARAMETER_KEYS) if parameter_schema else 0.0,
                  5.0, bounds_pass, {
                      "schema_exact": parameter_schema, "bounds": BOUNDS,
                      "submitted": {key: raw_parameters.get(key) for key in PARAMETER_KEYS},
                      "individual_pass": individual_bounds,
                      "artifact_error": parameter_error,
                  }),
        criterion("date_and_period", date_period_earned, 10.0, date_period_pass, {
            "matching_rows": date_matches, "expected_rows": len(source),
            "submitted_rows": len(daily_rows), "unique_dates": date_unique,
            "artifact_error": daily_error,
        }),
        criterion("daily_values", 15.0 * daily_ratio, 15.0, daily_pass, {
            "observed_values_correct": observed_correct, "simulated_values_correct": simulated_correct,
            "expected_rows": len(source), "simulated_absolute_tolerance": 1e-5,
            "continuous_state_from_warmup_through_validation": True,
        }),
        criterion("calibration_validation_performance", performance_earned, 25.0, performance_pass, {
            "calibration_nse": calibration_nse if math.isfinite(calibration_nse) else None,
            "calibration_threshold": 0.98,
            "validation_nse": validation_nse if math.isfinite(validation_nse) else None,
            "validation_threshold": 0.95,
            "validation_kge_diagnostic": validation_kge if math.isfinite(validation_kge) else None,
        }),
        criterion("metrics_consistency", metrics_earned, 10.0, metrics_pass, {
            "schema_exact": metric_schema, "per_metric_pass": metric_matches,
            "recomputed_from_continuous_model": {
                key: value if math.isfinite(value) else None for key, value in recomputed_metrics.items()
            },
            "recomputed_from_submitted_daily_artifact": submitted_daily_metrics,
            "absolute_tolerance": 1e-5,
            "artifact_error": metrics_error,
        }),
        criterion("calibration_script_exists", 10.0 if script_pass else 0.0, 10.0, script_pass, script_details),
        criterion("report_exists", 5.0 if report_pass else 0.0, 5.0, report_pass, {
            "path": "output/report.md", "nonempty": report_pass,
        }),
    ]
    hard_gates = {
        "parameters_in_bounds": bounds_pass,
        "continuous_simulation_correct": date_period_pass and daily_pass,
        "calibration_and_validation_skill": performance_pass,
        "metrics_consistent": metrics_pass,
        "required_artifacts": script_pass and report_pass,
    }
    failure_codes = []
    for passed, code in [
        (bounds_pass, "PARAMETER_SCHEMA_OR_BOUNDS"),
        (date_period_pass, "DATE_PERIOD_SPLIT_MISMATCH"),
        (daily_pass, "DAILY_WATER_BALANCE_MISMATCH"),
        (performance_pass, "MODEL_SKILL_BELOW_THRESHOLD"),
        (metrics_pass, "METRICS_MISMATCH"),
        (script_pass, "MISSING_CALIBRATION_SCRIPT"),
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
