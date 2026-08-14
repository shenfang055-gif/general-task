#!/usr/bin/env python3
"""Deterministic artifact grader for life-l1-cell-annotation.

Only Python's standard library is required.  The expected annotations are
derived from the task inputs and marker signatures below; no submission code
is imported or executed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


TASK_ID = "life-l1-cell-annotation"
CRITERION_MAXIMA = [
    ("D1_schema_coverage", 10.0),
    ("D2_marker_supported_labels", 45.0),
    ("D3_evidence_markers", 15.0),
    ("D4_report_exists", 10.0),
]

# These are domain rules, not fixture-specific answers.  Mean signature
# intensity selects the label; the narrower evidence set lists markers that a
# submitted explanation must cite for full evidence credit.
SIGNATURES: Dict[str, Tuple[str, ...]] = {
    "CD4 T cell": ("CD3", "CD4"),
    "CD8 T cell": ("CD3", "CD8"),
    "B cell": ("CD20",),
    "Macrophage": ("CD68", "CD163"),
    "Regulatory T cell": ("CD3", "CD4", "FOXP3"),
    "Hodgkin tumor cell": ("CD30",),
}
REQUIRED_EVIDENCE: Dict[str, Set[str]] = {
    "CD4 T cell": {"CD3", "CD4"},
    "CD8 T cell": {"CD3", "CD8"},
    "B cell": {"CD20"},
    "Macrophage": {"CD68", "CD163"},
    "Regulatory T cell": {"CD4", "FOXP3"},
    "Hodgkin tumor cell": {"CD30"},
}
UNASSIGNED_MIN_SCORE = 2.0


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


def _finite(value: str, context: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{context} is not finite")
    return parsed


def _load_truth(inputs: Path) -> Tuple[Dict[str, str], Set[str], Set[str]]:
    vocab_fields, vocab_rows = _read_csv(inputs / "cell_type_vocabulary.csv")
    if vocab_fields != ["cell_type"]:
        raise ValueError("cell_type_vocabulary.csv schema must be exactly cell_type")
    vocabulary = {row["cell_type"] for row in vocab_rows if row["cell_type"]}
    if len(vocabulary) != len(vocab_rows) or not set(SIGNATURES).issubset(vocabulary):
        raise ValueError("cell-type vocabulary is duplicate or lacks required labels")

    marker_fields, marker_rows = _read_csv(inputs / "cluster_markers.csv")
    required_columns = {"cluster", "n_cells"}.union(
        marker for signature in SIGNATURES.values() for marker in signature
    )
    if not required_columns.issubset(marker_fields):
        raise ValueError("cluster_markers.csv lacks required marker columns")
    marker_columns = set(marker_fields) - {"cluster", "n_cells"}
    expected: Dict[str, str] = {}
    for row in marker_rows:
        cluster = row["cluster"]
        if not cluster or cluster in expected:
            raise ValueError("cluster_markers.csv has blank or duplicate cluster IDs")
        n_cells = _finite(row["n_cells"], f"cluster {cluster} n_cells")
        if n_cells <= 0 or not n_cells.is_integer():
            raise ValueError(f"cluster {cluster} has invalid n_cells")
        values = {
            marker: _finite(row[marker], f"cluster {cluster} {marker}")
            for marker in marker_columns
        }
        scores = {
            label: sum(values[marker] for marker in signature) / len(signature)
            for label, signature in SIGNATURES.items()
        }
        winner, best_score = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[0]
        expected[cluster] = winner if best_score >= UNASSIGNED_MIN_SCORE else "Unassigned"
    if not expected:
        raise ValueError("cluster_markers.csv contains no clusters")
    return expected, vocabulary, marker_columns


def _report_state(path: Path) -> Tuple[bool, bool, str]:
    if not _regular_file(path):
        return False, False, "report.md is missing or is not a regular file"
    try:
        if path.stat().st_size > 1_000_000:
            return True, False, "report.md exceeds the 1 MB grader safety limit"
        text = path.read_text(encoding="utf-8").strip()
    except Exception as exc:
        return True, False, f"report.md is unreadable: {exc}"
    if not text:
        return True, False, "report.md is empty"

    # High-precision phrases only.  Broader scientific restraint remains part
    # of the blind JudgeScore rather than a brittle keyword heuristic.
    positive_diagnosis = re.compile(
        r"(?:确诊为|诊断结果为|可诊断为|diagnosed\s+with|clinical\s+diagnosis\s+is)",
        flags=re.IGNORECASE,
    )
    non_diagnostic = not bool(positive_diagnosis.search(text))
    return True, non_diagnostic, (
        "report is present and contains no explicit clinical-diagnosis claim"
        if non_diagnostic
        else "report contains an explicit clinical-diagnosis claim"
    )


def grade(workspace: Path) -> Dict[str, Any]:
    try:
        expected, vocabulary, marker_columns = _load_truth(workspace / "inputs")
    except Exception as exc:
        return _empty_result("error", "INPUT_INVALID", f"cannot derive truth: {exc}")

    main_path = workspace / "output" / "cell_annotations.csv"
    if not _regular_file(main_path):
        return _empty_result("ok", "MAIN_ARTIFACT_MISSING", str(main_path))
    try:
        fields, rows = _read_csv(main_path)
    except Exception as exc:
        return _empty_result("ok", "MAIN_ARTIFACT_PARSE_ERROR", str(exc))

    failures: List[str] = []
    strict_schema = fields == ["cluster", "cell_type", "evidence_markers"]
    if not strict_schema:
        failures.append("SCHEMA_MISMATCH")

    required_keys = {"cluster", "cell_type", "evidence_markers"}
    usable_rows = rows if required_keys.issubset(fields) else []
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in usable_rows:
        grouped.setdefault(row["cluster"], []).append(row)
    submitted_ids = set(grouped)
    expected_ids = set(expected)
    unique_expected_rows = all(len(grouped.get(cluster, [])) == 1 for cluster in expected_ids)
    no_extra_or_blank = submitted_ids == expected_ids and "" not in submitted_ids
    coverage_ok = unique_expected_rows and no_extra_or_blank and len(rows) == len(expected_ids)
    vocab_ok = bool(usable_rows) and all(row["cell_type"] in vocabulary for row in usable_rows)
    if not coverage_ok:
        failures.append("CLUSTER_COVERAGE_OR_UNIQUENESS_MISMATCH")
    if not vocab_ok:
        failures.append("LABEL_OUTSIDE_VOCABULARY")

    schema_points = 4.0 if strict_schema else 0.0
    coverage_points = 4.0 if coverage_ok else 0.0
    vocab_points = 2.0 if vocab_ok else 0.0
    schema_earned = schema_points + coverage_points + vocab_points

    correct_labels: List[str] = []
    correct_evidence: List[str] = []
    invalid_evidence: Dict[str, List[str]] = {}
    for cluster, expected_label in expected.items():
        cluster_rows = grouped.get(cluster, [])
        if len(cluster_rows) != 1:
            continue
        row = cluster_rows[0]
        if row["cell_type"] == expected_label:
            correct_labels.append(cluster)
        supplied = {
            marker.strip().upper()
            for marker in row["evidence_markers"].split(";")
            if marker.strip()
        }
        unknown = supplied.difference({marker.upper() for marker in marker_columns})
        if unknown:
            invalid_evidence[cluster] = sorted(unknown)
        required = REQUIRED_EVIDENCE.get(expected_label, set())
        if row["cell_type"] == expected_label and required.issubset(supplied) and not unknown:
            correct_evidence.append(cluster)

    label_earned = 45.0 * len(correct_labels) / len(expected)
    evidence_earned = 15.0 * len(correct_evidence) / len(expected)
    labels_ok = len(correct_labels) == len(expected)
    evidence_ok = len(correct_evidence) == len(expected)
    if not labels_ok:
        failures.append("MARKER_IDENTITY_MISMATCH")
    if not evidence_ok:
        failures.append("EVIDENCE_MARKER_MISMATCH")

    report_exists, report_non_diagnostic, report_details = _report_state(
        workspace / "output" / "report.md"
    )
    report_ok = report_exists and report_non_diagnostic
    if not report_exists:
        failures.append("REPORT_MISSING_OR_INVALID")
    elif not report_non_diagnostic:
        failures.append("REPORT_CLINICAL_OVERCLAIM")

    criteria = [
        _criterion(
            "D1_schema_coverage",
            schema_earned,
            10.0,
            strict_schema and coverage_ok and vocab_ok,
            {
                "strict_schema": strict_schema,
                "complete_unique_cluster_set": coverage_ok,
                "all_labels_in_input_vocabulary": vocab_ok,
                "missing_clusters": sorted(expected_ids - submitted_ids),
                "extra_clusters": sorted(submitted_ids - expected_ids),
            },
        ),
        _criterion(
            "D2_marker_supported_labels",
            label_earned,
            45.0,
            labels_ok,
            {"correct_clusters": sorted(correct_labels), "total_clusters": len(expected)},
        ),
        _criterion(
            "D3_evidence_markers",
            evidence_earned,
            15.0,
            evidence_ok,
            {
                "clusters_with_sufficient_evidence": sorted(correct_evidence),
                "unknown_markers": invalid_evidence,
                "total_clusters": len(expected),
            },
        ),
        _criterion(
            "D4_report_exists",
            10.0 if report_exists else 0.0,
            10.0,
            report_exists,
            report_details,
        ),
    ]
    hardgates = {
        "complete_unique_clusters_and_vocabulary": strict_schema and coverage_ok and vocab_ok,
        "annotations_match_marker_identity": labels_ok,
        "report_present_and_non_diagnostic": report_ok,
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
