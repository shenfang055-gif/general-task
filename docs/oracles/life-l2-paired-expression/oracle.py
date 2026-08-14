#!/usr/bin/env python3
"""Deterministic artifact grader for life-l2-paired-expression.

The scientific truth is recomputed from ``inputs/`` with Python's standard
library.  Submission code is never imported or executed.  The script criterion
is a static source check only; true reproducibility reruns belong in a separately
isolated CI/container outside this artifact grader.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


TASK_ID = "life-l2-paired-expression"
OUTPUT_COLUMNS = ["gene_id", "mean_paired_delta", "direction"]
CRITERION_MAXIMA = [
    ("D1_schema_gene_coverage", 10.0),
    ("D2_paired_delta", 40.0),
    ("D3_direction", 15.0),
    ("D4_summary_consistency", 5.0),
    ("D5_script_static_check", 10.0),
]
ABS_TOLERANCE = 1e-6


def _criterion(
    criterion_id: str, earned: float, maximum: float, passed: bool, details: Any
) -> Dict[str, Any]:
    return {
        "id": criterion_id,
        "earned": round(max(0.0, min(maximum, earned)), 3),
        "max": maximum,
        "pass": bool(passed),
        "details": details,
    }


def _empty_result(status: str, code: str, details: str) -> Dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "grader_status": status,
        "hardgate_pass": False,
        "deterministic_score": 0.0,
        "criteria": [
            _criterion(cid, 0.0, maximum, False, details)
            for cid, maximum in CRITERION_MAXIMA
        ],
        "failure_codes": [code],
    }


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _read_csv(path: Path, delimiter: str = ",") -> Tuple[List[str], List[Dict[str, str]]]:
    if not _regular_file(path):
        raise FileNotFoundError(str(path))
    if path.stat().st_size > 10_000_000:
        raise ValueError(f"{path.name} exceeds 10 MB")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError(f"{path.name} has no header")
        fields = [field.strip() for field in reader.fieldnames]
        if len(fields) != len(set(fields)):
            raise ValueError(f"{path.name} has duplicate columns")
        rows: List[Dict[str, str]] = []
        for raw in reader:
            if None in raw:
                raise ValueError(f"{path.name} contains rows wider than its header")
            rows.append({key.strip(): (value or "").strip() for key, value in raw.items()})
    return fields, rows


def _finite(value: Any, context: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{context} is not finite")
    return parsed


def _close(actual: float, expected: float) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= ABS_TOLERANCE


def _direction(delta: float) -> str:
    if delta >= 0.5:
        return "up"
    if delta <= -0.5:
        return "down"
    return "stable"


def _load_truth(inputs: Path) -> Tuple[Dict[str, Tuple[float, str]], Dict[str, Any]]:
    metadata_fields, metadata_rows = _read_csv(inputs / "metadata.csv")
    if metadata_fields != ["sample_id", "donor", "condition", "batch"]:
        raise ValueError("metadata.csv has an unexpected schema")
    metadata: Dict[str, Dict[str, str]] = {}
    for row in metadata_rows:
        sample = row["sample_id"]
        if not sample or sample in metadata:
            raise ValueError("metadata.csv has blank or duplicate sample IDs")
        if row["condition"] not in {"control", "treated"}:
            raise ValueError(f"sample {sample} has invalid condition")
        if not row["donor"] or not row["batch"]:
            raise ValueError(f"sample {sample} lacks donor or batch")
        metadata[sample] = row

    expression_fields, expression_rows = _read_csv(
        inputs / "expression_log2cpm.tsv", delimiter="\t"
    )
    if not expression_fields or expression_fields[0] != "gene_id":
        raise ValueError("expression matrix must start with gene_id")
    sample_columns = expression_fields[1:]
    if not sample_columns or len(sample_columns) != len(set(sample_columns)):
        raise ValueError("expression matrix has no samples or duplicate sample columns")
    if set(sample_columns) != set(metadata):
        raise ValueError("expression and metadata sample-ID sets differ")

    donor_pairs: Dict[str, Dict[str, str]] = {}
    for sample, row in metadata.items():
        per_donor = donor_pairs.setdefault(row["donor"], {})
        condition = row["condition"]
        if condition in per_donor:
            raise ValueError(f"donor {row['donor']} has duplicate {condition} samples")
        per_donor[condition] = sample
    if not donor_pairs or any(set(pair) != {"control", "treated"} for pair in donor_pairs.values()):
        raise ValueError("every donor must have exactly one control and one treated sample")

    expected: Dict[str, Tuple[float, str]] = {}
    for row in expression_rows:
        gene = row["gene_id"]
        if not gene or gene in expected:
            raise ValueError("expression matrix has blank or duplicate gene IDs")
        values = {
            sample: _finite(row[sample], f"gene {gene}, sample {sample}")
            for sample in sample_columns
        }
        deltas = [
            values[pair["treated"]] - values[pair["control"]]
            for pair in donor_pairs.values()
        ]
        mean_delta = sum(deltas) / len(deltas)
        expected[gene] = (mean_delta, _direction(mean_delta))
    if not expected:
        raise ValueError("expression matrix contains no genes")

    top_up = sorted(expected, key=lambda gene: (-expected[gene][0], gene))[0]
    top_down = sorted(expected, key=lambda gene: (expected[gene][0], gene))[0]
    summary = {
        "top_up_gene": top_up,
        "top_down_gene": top_down,
        "n_donors": len(donor_pairs),
    }
    return expected, summary


def _read_summary(path: Path) -> Dict[str, Any]:
    if not _regular_file(path):
        raise FileNotFoundError(str(path))
    if path.stat().st_size > 1_000_000:
        raise ValueError("summary.json exceeds 1 MB")

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant {value}")

    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("summary.json must contain a JSON object")
    return value


def _evaluate_main(
    path: Path, expected: Dict[str, Tuple[float, str]]
) -> Tuple[Dict[str, Any], Optional[Dict[str, Dict[str, str]]]]:
    fields, rows = _read_csv(path)
    strict_schema = fields == OUTPUT_COLUMNS
    if not set(OUTPUT_COLUMNS).issubset(fields):
        return {
            "strict_schema": strict_schema,
            "coverage_ok": False,
            "correct_numeric": [],
            "correct_direction": [],
            "parse_errors": ["required columns are absent"],
            "missing_genes": sorted(expected),
            "extra_genes": [],
        }, None

    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["gene_id"], []).append(row)
    expected_ids = set(expected)
    actual_ids = set(grouped)
    coverage_ok = (
        actual_ids == expected_ids
        and "" not in actual_ids
        and len(rows) == len(expected_ids)
        and all(len(grouped[gene]) == 1 for gene in expected_ids)
    )
    correct_numeric: List[str] = []
    correct_direction: List[str] = []
    parse_errors: List[str] = []
    by_gene: Dict[str, Dict[str, str]] = {}
    for gene, (expected_delta, expected_direction) in expected.items():
        gene_rows = grouped.get(gene, [])
        if len(gene_rows) != 1:
            continue
        row = gene_rows[0]
        by_gene[gene] = row
        try:
            actual_delta = _finite(row["mean_paired_delta"], f"output gene {gene}")
            if _close(actual_delta, expected_delta):
                correct_numeric.append(gene)
            if row["direction"] == expected_direction and row["direction"] == _direction(actual_delta):
                correct_direction.append(gene)
        except Exception as exc:
            parse_errors.append(str(exc))
    return {
        "strict_schema": strict_schema,
        "coverage_ok": coverage_ok,
        "correct_numeric": sorted(correct_numeric),
        "correct_direction": sorted(correct_direction),
        "parse_errors": parse_errors,
        "missing_genes": sorted(expected_ids - actual_ids),
        "extra_genes": sorted(actual_ids - expected_ids),
    }, by_gene


def _script_static_check(workspace: Path) -> Tuple[bool, Dict[str, Any]]:
    script = workspace / "output" / "analyze.py"
    if not _regular_file(script):
        return False, {"status": "missing", "detail": "output/analyze.py is missing"}
    if script.stat().st_size > 1_000_000:
        return False, {"status": "unsafe", "detail": "analyze.py exceeds 1 MB"}
    try:
        source = script.read_text(encoding="utf-8")
        if not source.strip():
            return False, {"status": "empty", "detail": "analyze.py is empty"}
        ast.parse(source, filename="analyze.py")
        mentions_inputs = "inputs" in source
        mentions_main_output = "paired_effects.csv" in source
        ok = mentions_inputs and mentions_main_output
        return ok, {
            "status": "passed" if ok else "incomplete",
            "utf8_nonempty_ast_parseable": True,
            "mentions_inputs": mentions_inputs,
            "mentions_paired_effects_csv": mentions_main_output,
            "detail": (
                "static check only; submission code was not executed. A clean rerun must be "
                "performed later in isolated CI/container."
            ),
        }
    except Exception as exc:
        return False, {
            "status": "invalid",
            "detail": (
                f"static source check failed: {exc}. Submission code was not executed; "
                "a clean rerun belongs in isolated CI/container."
            ),
        }


def grade(workspace: Path) -> Dict[str, Any]:
    try:
        expected, expected_summary = _load_truth(workspace / "inputs")
    except Exception as exc:
        return _empty_result("error", "INPUT_INVALID", f"cannot derive truth: {exc}")

    main_path = workspace / "output" / "paired_effects.csv"
    if not _regular_file(main_path):
        return _empty_result("ok", "MAIN_ARTIFACT_MISSING", str(main_path))
    try:
        checks, by_gene = _evaluate_main(main_path, expected)
    except Exception as exc:
        return _empty_result("ok", "MAIN_ARTIFACT_PARSE_ERROR", str(exc))

    failures: List[str] = []
    if not checks["strict_schema"]:
        failures.append("SCHEMA_MISMATCH")
    if not checks["coverage_ok"]:
        failures.append("GENE_COVERAGE_OR_UNIQUENESS_MISMATCH")
    if checks["parse_errors"]:
        failures.append("NONFINITE_OR_INVALID_DELTA")

    numeric_count = len(checks["correct_numeric"])
    direction_count = len(checks["correct_direction"])
    numeric_ok = numeric_count == len(expected)
    direction_ok = direction_count == len(expected)
    if not numeric_ok:
        failures.append("PAIRED_DELTA_MISMATCH")
    if not direction_ok:
        failures.append("CONTRAST_DIRECTION_MISMATCH")

    summary_ok = False
    summary_details: Dict[str, Any]
    try:
        summary = _read_summary(workspace / "output" / "summary.json")
        keys_ok = all(key in summary for key in expected_summary)
        types_ok = (
            isinstance(summary.get("top_up_gene"), str)
            and isinstance(summary.get("top_down_gene"), str)
            and isinstance(summary.get("n_donors"), int)
            and not isinstance(summary.get("n_donors"), bool)
        )
        truth_ok = keys_ok and types_ok and all(
            summary.get(key) == value for key, value in expected_summary.items()
        )
        artifact_ok = False
        if by_gene and len(by_gene) == len(expected):
            try:
                submitted_delta = {
                    gene: _finite(row["mean_paired_delta"], f"output gene {gene}")
                    for gene, row in by_gene.items()
                }
                artifact_top_up = sorted(
                    submitted_delta, key=lambda gene: (-submitted_delta[gene], gene)
                )[0]
                artifact_top_down = sorted(
                    submitted_delta, key=lambda gene: (submitted_delta[gene], gene)
                )[0]
                artifact_ok = (
                    summary.get("top_up_gene") == artifact_top_up
                    and summary.get("top_down_gene") == artifact_top_down
                )
            except Exception:
                artifact_ok = False
        summary_ok = truth_ok and artifact_ok
        summary_details = {
            "required_keys_and_types": keys_ok and types_ok,
            "matches_input_derived_truth": truth_ok,
            "matches_main_artifact": artifact_ok,
        }
    except Exception as exc:
        summary_details = {"error": str(exc)}
    if not summary_ok:
        failures.append("SUMMARY_MISSING_INVALID_OR_INCONSISTENT")

    report_ok = _regular_file(workspace / "output" / "report.md")
    if not report_ok:
        failures.append("REPORT_MISSING")

    script_ok, script_details = _script_static_check(workspace)
    if not script_ok:
        failures.append("SCRIPT_MISSING_OR_STATIC_CHECK_FAILED")

    schema_earned = (4.0 if checks["strict_schema"] else 0.0) + (
        6.0 if checks["coverage_ok"] else 0.0
    )
    criteria = [
        _criterion(
            "D1_schema_gene_coverage",
            schema_earned,
            10.0,
            checks["strict_schema"] and checks["coverage_ok"],
            {
                "strict_schema": checks["strict_schema"],
                "complete_unique_gene_set": checks["coverage_ok"],
                "missing_genes": checks["missing_genes"],
                "extra_genes": checks["extra_genes"],
            },
        ),
        _criterion(
            "D2_paired_delta",
            40.0 * numeric_count / len(expected),
            40.0,
            numeric_ok,
            {
                "correct_genes": checks["correct_numeric"],
                "total_genes": len(expected),
                "absolute_tolerance": ABS_TOLERANCE,
                "parse_errors": checks["parse_errors"],
            },
        ),
        _criterion(
            "D3_direction",
            15.0 * direction_count / len(expected),
            15.0,
            direction_ok,
            {
                "correct_genes": checks["correct_direction"],
                "total_genes": len(expected),
                "thresholds": {"up": ">=0.5", "down": "<=-0.5", "otherwise": "stable"},
            },
        ),
        _criterion(
            "D4_summary_consistency",
            5.0 if summary_ok else 0.0,
            5.0,
            summary_ok,
            summary_details,
        ),
        _criterion(
            "D5_script_static_check",
            10.0 if script_ok else 0.0,
            10.0,
            script_ok,
            script_details,
        ),
    ]
    hardgates = {
        "id_join_and_complete_gene_set": checks["strict_schema"] and checks["coverage_ok"],
        "paired_treated_minus_control_numeric": numeric_ok,
        "direction_and_finite_values": direction_ok and not checks["parse_errors"],
        "all_deliverables_parseable": summary_ok and report_ok and script_ok,
        "script_present_and_statically_valid": script_ok,
    }
    return {
        "task_id": TASK_ID,
        "grader_status": "ok",
        "hardgate_pass": all(hardgates.values()),
        "deterministic_score": round(sum(item["earned"] for item in criteria), 3),
        "criteria": criteria,
        "hardgates": hardgates,
        "failure_codes": sorted(set(failures)),
    }


def _write_result(result: Dict[str, Any], out_path: Optional[Path]) -> Dict[str, Any]:
    if out_path is not None:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except Exception as exc:
            result = dict(result)
            result["grader_status"] = "error"
            result["hardgate_pass"] = False
            result["failure_codes"] = sorted(
                set(result.get("failure_codes", []) + ["GRADER_OUTPUT_WRITE_ERROR"])
            )
            result["grader_error"] = str(exc)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    exit_code = 0
    try:
        result = grade(args.workspace.resolve())
    except Exception as exc:  # final guard: never leak a grading traceback
        result = _empty_result("error", "GRADER_INTERNAL_ERROR", str(exc))
        exit_code = 2
    result = _write_result(result, args.out)
    if result.get("grader_status") == "error":
        exit_code = 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
