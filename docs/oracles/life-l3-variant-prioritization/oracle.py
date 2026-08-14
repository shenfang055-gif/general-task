#!/usr/bin/env python3
"""Deterministic artifact grader for life-l3-variant-prioritization.

The expected candidate set is derived from method_note.md, pedigree.csv,
gene_panel.csv, and variants.csv.  The stale output and legacy implementation
are never used as truth.  Submission code is never imported or executed; the
script criterion is a static source check and an actual rerun is deferred to a
separately isolated CI/container.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


TASK_ID = "life-l3-variant-prioritization"
CANDIDATE_COLUMNS = ["variant_id", "gene", "inheritance_model", "parental_origin"]
SUMMARY_COLUMNS = ["gene", "inheritance_model", "qualifying_variants"]
CRITERION_MAXIMA = [
    ("D1_candidate_set_schema", 15.0),
    ("D2_variant_rules_and_origin", 35.0),
    ("D3_gene_summary_consistency", 15.0),
    ("D4_script_static_check", 10.0),
    ("D5_report_exists", 5.0),
]


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


def _read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    if not _regular_file(path):
        raise FileNotFoundError(str(path))
    if path.stat().st_size > 20_000_000:
        raise ValueError(f"{path.name} exceeds 20 MB")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
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


def _integer(value: str, context: str) -> int:
    parsed = _finite(value, context)
    if not parsed.is_integer():
        raise ValueError(f"{context} is not an integer")
    return int(parsed)


def _parse_method_note(path: Path) -> Dict[str, Any]:
    if not _regular_file(path):
        raise FileNotFoundError(str(path))
    text = path.read_text(encoding="utf-8")

    def extract(pattern: str, name: str, flags: int = re.IGNORECASE) -> str:
        match = re.search(pattern, text, flags=flags)
        if not match:
            raise ValueError(f"method_note.md does not define {name}")
        return match.group(1)

    proband = extract(r"affected proband is `([^`]+)`", "affected proband")
    father = extract(r"parents `([^`]+)` and `([^`]+)`", "parents")
    parent_match = re.search(r"parents `([^`]+)` and `([^`]+)`", text, flags=re.IGNORECASE)
    if not parent_match:
        raise ValueError("method_note.md does not define parents")
    father, mother = parent_match.group(1), parent_match.group(2)
    dp_min = int(extract(r"DP\s*>=\s*(\d+)", "minimum DP"))
    gq_min = int(extract(r"GQ\s*>=\s*(\d+)", "minimum GQ"))
    af_max = float(
        extract(r"allele frequency\s*`?\s*<\s*([0-9.]+)", "maximum AF")
    )
    consequence_text = extract(
        r"consequence in\s+(.+?)\.\s*\n", "allowed consequences", flags=re.IGNORECASE | re.DOTALL
    )
    consequences = set(re.findall(r"`([^`]+)`", consequence_text))
    if not consequences:
        raise ValueError("method_note.md has no allowed consequences")
    return {
        "proband": proband,
        "father": father,
        "mother": mother,
        "dp_min": dp_min,
        "gq_min": gq_min,
        "af_max": af_max,
        "consequences": consequences,
    }


def _parse_genotype(value: str, context: str) -> Tuple[int, int]:
    match = re.fullmatch(r"([0-9]+)[/|]([0-9]+)", value.strip())
    if not match:
        raise ValueError(f"{context} has invalid diploid genotype {value!r}")
    return int(match.group(1)), int(match.group(2))


def _is_ref(genotype: Tuple[int, int]) -> bool:
    return genotype == (0, 0)


def _is_het(genotype: Tuple[int, int]) -> bool:
    return sorted(genotype) == [0, 1]


def _load_truth(inputs: Path) -> Tuple[Dict[str, Tuple[str, str, str]], Dict[str, Tuple[str, int]]]:
    rules = _parse_method_note(inputs / "method_note.md")

    pedigree_fields, pedigree_rows = _read_csv(inputs / "pedigree.csv")
    if pedigree_fields != ["sample_id", "role", "affected"]:
        raise ValueError("pedigree.csv has an unexpected schema")
    by_role: Dict[str, str] = {}
    for row in pedigree_rows:
        role = row["role"]
        if role in by_role or not row["sample_id"]:
            raise ValueError("pedigree.csv has duplicate roles or blank sample IDs")
        by_role[role] = row["sample_id"]
    if by_role.get("proband") != rules["proband"]:
        raise ValueError("method note and pedigree disagree on proband")
    if by_role.get("father") != rules["father"] or by_role.get("mother") != rules["mother"]:
        raise ValueError("method note and pedigree disagree on parents")

    panel_fields, panel_rows = _read_csv(inputs / "gene_panel.csv")
    if panel_fields != ["gene", "inheritance"]:
        raise ValueError("gene_panel.csv has an unexpected schema")
    panel: Dict[str, str] = {}
    for row in panel_rows:
        if not row["gene"] or row["gene"] in panel:
            raise ValueError("gene_panel.csv has blank or duplicate genes")
        if row["inheritance"] not in {"AD_de_novo", "AR_compound_het"}:
            raise ValueError(f"unsupported inheritance label {row['inheritance']}")
        panel[row["gene"]] = row["inheritance"]

    required_variant_columns = [
        "variant_id", "sample_id", "chrom", "pos", "ref", "alt", "gene",
        "consequence", "gnomad_af", "genotype", "dp", "gq",
    ]
    variant_fields, variant_rows = _read_csv(inputs / "variants.csv")
    if variant_fields != required_variant_columns:
        raise ValueError("variants.csv has an unexpected schema")
    by_variant: Dict[str, Dict[str, Dict[str, Any]]] = {}
    variant_identity: Dict[str, Tuple[str, str, str, str, str, str]] = {}
    allowed_samples = {rules["proband"], rules["father"], rules["mother"]}
    for row in variant_rows:
        variant = row["variant_id"]
        sample = row["sample_id"]
        if not variant or sample not in allowed_samples:
            raise ValueError("variants.csv has blank variant or unexpected sample")
        identity = tuple(row[key] for key in ("chrom", "pos", "ref", "alt", "gene", "consequence"))
        if variant in variant_identity and variant_identity[variant] != identity:
            raise ValueError(f"variant {variant} has inconsistent identity across samples")
        variant_identity[variant] = identity
        per_sample = by_variant.setdefault(variant, {})
        if sample in per_sample:
            raise ValueError(f"variant {variant} has duplicate row for sample {sample}")
        per_sample[sample] = {
            **row,
            "af": _finite(row["gnomad_af"], f"variant {variant} AF"),
            "dp": _integer(row["dp"], f"variant {variant} DP"),
            "gq": _integer(row["gq"], f"variant {variant} GQ"),
            "gt": _parse_genotype(row["genotype"], f"variant {variant}, sample {sample}"),
        }
    if not by_variant or any(set(per_sample) != allowed_samples for per_sample in by_variant.values()):
        raise ValueError("every variant must contain exactly the trio sample set")

    base_qualifying: Dict[str, Dict[str, Any]] = {}
    for variant, trio in by_variant.items():
        proband = trio[rules["proband"]]
        gene = proband["gene"]
        if (
            gene in panel
            and proband["dp"] >= rules["dp_min"]
            and proband["gq"] >= rules["gq_min"]
            and 0.0 <= proband["af"] < rules["af_max"]
            and proband["consequence"] in rules["consequences"]
            and _is_het(proband["gt"])
        ):
            base_qualifying[variant] = {
                "gene": gene,
                "model": panel[gene],
                "father_ref": _is_ref(trio[rules["father"]]["gt"]),
                "mother_ref": _is_ref(trio[rules["mother"]]["gt"]),
                "father_het": _is_het(trio[rules["father"]]["gt"]),
                "mother_het": _is_het(trio[rules["mother"]]["gt"]),
            }

    candidates: Dict[str, Tuple[str, str, str]] = {}
    compound_groups: Dict[str, List[Tuple[str, str]]] = {}
    for variant, item in base_qualifying.items():
        if item["model"] == "AD_de_novo":
            if item["father_ref"] and item["mother_ref"]:
                candidates[variant] = (item["gene"], "de_novo", "none")
        elif item["model"] == "AR_compound_het":
            origin: Optional[str] = None
            if item["father_het"] and item["mother_ref"]:
                origin = "father"
            elif item["mother_het"] and item["father_ref"]:
                origin = "mother"
            if origin:
                compound_groups.setdefault(item["gene"], []).append((variant, origin))
    for gene, items in compound_groups.items():
        origins = {origin for _, origin in items}
        if len(items) >= 2 and {"father", "mother"}.issubset(origins):
            for variant, origin in items:
                candidates[variant] = (gene, "compound_het", origin)

    summary_counts: Dict[Tuple[str, str], int] = {}
    for gene, model, _origin in candidates.values():
        summary_counts[(gene, model)] = summary_counts.get((gene, model), 0) + 1
    summary = {gene: (model, count) for (gene, model), count in summary_counts.items()}
    return candidates, summary


def _evaluate_candidates(
    path: Path, expected: Dict[str, Tuple[str, str, str]]
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, str]]]:
    fields, rows = _read_csv(path)
    strict_schema = fields == CANDIDATE_COLUMNS
    if not set(CANDIDATE_COLUMNS).issubset(fields):
        return {
            "strict_schema": strict_schema,
            "exact_set": False,
            "correct_variants": [],
            "missing_variants": sorted(expected),
            "extra_variants": [],
        }, {}
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["variant_id"], []).append(row)
    actual_ids = set(grouped)
    expected_ids = set(expected)
    exact_set = (
        actual_ids == expected_ids
        and "" not in actual_ids
        and len(rows) == len(expected_ids)
        and all(len(grouped[variant]) == 1 for variant in expected_ids)
    )
    by_variant = {
        variant: variant_rows[0]
        for variant, variant_rows in grouped.items()
        if len(variant_rows) == 1
    }
    correct = []
    for variant, values in expected.items():
        row = by_variant.get(variant, {})
        if tuple(row.get(column) for column in CANDIDATE_COLUMNS[1:]) == values:
            correct.append(variant)
    return {
        "strict_schema": strict_schema,
        "exact_set": exact_set,
        "correct_variants": sorted(correct),
        "missing_variants": sorted(expected_ids - actual_ids),
        "extra_variants": sorted(actual_ids - expected_ids),
    }, by_variant


def _evaluate_summary(
    path: Path,
    expected: Dict[str, Tuple[str, int]],
    submitted_candidates: Dict[str, Dict[str, str]],
) -> Tuple[bool, Dict[str, Any]]:
    fields, rows = _read_csv(path)
    strict_schema = fields == SUMMARY_COLUMNS
    if not set(SUMMARY_COLUMNS).issubset(fields):
        return False, {"strict_schema": strict_schema, "error": "required columns are absent"}
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["gene"], []).append(row)
    exact_genes = (
        set(grouped) == set(expected)
        and "" not in grouped
        and len(rows) == len(expected)
        and all(len(grouped[gene]) == 1 for gene in expected)
    )
    parsed: Dict[str, Tuple[str, int]] = {}
    parse_errors: List[str] = []
    for gene, gene_rows in grouped.items():
        if len(gene_rows) != 1:
            continue
        row = gene_rows[0]
        try:
            count = _integer(row["qualifying_variants"], f"summary gene {gene}")
            if count < 0:
                raise ValueError(f"summary gene {gene} count is negative")
            parsed[gene] = (row["inheritance_model"], count)
        except Exception as exc:
            parse_errors.append(str(exc))
    truth_ok = parsed == expected
    from_candidates: Dict[str, Tuple[str, int]] = {}
    candidate_valid = True
    counts: Dict[Tuple[str, str], int] = {}
    for row in submitted_candidates.values():
        gene = row.get("gene", "")
        model = row.get("inheritance_model", "")
        if not gene or not model:
            candidate_valid = False
            continue
        counts[(gene, model)] = counts.get((gene, model), 0) + 1
    for (gene, model), count in counts.items():
        if gene in from_candidates and from_candidates[gene] != (model, count):
            candidate_valid = False
        from_candidates[gene] = (model, count)
    cross_consistent = candidate_valid and parsed == from_candidates
    ok = strict_schema and exact_genes and truth_ok and cross_consistent and not parse_errors
    return ok, {
        "strict_schema": strict_schema,
        "complete_unique_gene_set": exact_genes,
        "matches_input_derived_truth": truth_ok,
        "matches_candidates_csv": cross_consistent,
        "parse_errors": parse_errors,
    }


def _script_static_check(workspace: Path) -> Tuple[bool, Dict[str, Any]]:
    script = workspace / "output" / "prioritize.py"
    if not _regular_file(script):
        return False, {"status": "missing", "detail": "output/prioritize.py is missing"}
    if script.stat().st_size > 1_000_000:
        return False, {"status": "unsafe", "detail": "prioritize.py exceeds 1 MB"}
    try:
        source = script.read_text(encoding="utf-8")
        if not source.strip():
            return False, {"status": "empty", "detail": "prioritize.py is empty"}
        ast.parse(source, filename="prioritize.py")
        mentions_inputs = "inputs" in source
        mentions_candidates = "candidates.csv" in source
        mentions_summary = "gene_summary.csv" in source
        mentions_stale = "stale_candidates.csv" in source
        ok = mentions_inputs and mentions_candidates and mentions_summary and not mentions_stale
        return ok, {
            "status": "passed" if ok else "incomplete",
            "utf8_nonempty_ast_parseable": True,
            "mentions_inputs": mentions_inputs,
            "mentions_candidates_csv": mentions_candidates,
            "mentions_gene_summary_csv": mentions_summary,
            "references_stale_candidates": mentions_stale,
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
        expected_candidates, expected_summary = _load_truth(workspace / "inputs")
    except Exception as exc:
        return _empty_result("error", "INPUT_INVALID", f"cannot derive truth: {exc}")

    main_path = workspace / "output" / "candidates.csv"
    if not _regular_file(main_path):
        return _empty_result("ok", "MAIN_ARTIFACT_MISSING", str(main_path))
    try:
        checks, submitted_candidates = _evaluate_candidates(main_path, expected_candidates)
    except Exception as exc:
        return _empty_result("ok", "MAIN_ARTIFACT_PARSE_ERROR", str(exc))

    failures: List[str] = []
    if not checks["strict_schema"]:
        failures.append("CANDIDATE_SCHEMA_MISMATCH")
    if not checks["exact_set"]:
        failures.append("CANDIDATE_SET_OR_UNIQUENESS_MISMATCH")
    correct_count = len(checks["correct_variants"])
    variant_rules_ok = correct_count == len(expected_candidates)
    if not variant_rules_ok:
        failures.append("VARIANT_RULE_OR_PARENTAL_ORIGIN_MISMATCH")

    summary_ok = False
    summary_details: Dict[str, Any]
    try:
        summary_ok, summary_details = _evaluate_summary(
            workspace / "output" / "gene_summary.csv",
            expected_summary,
            submitted_candidates,
        )
    except Exception as exc:
        summary_details = {"error": str(exc)}
    if not summary_ok:
        failures.append("GENE_SUMMARY_MISSING_INVALID_OR_INCONSISTENT")

    script_ok, script_details = _script_static_check(workspace)
    if not script_ok:
        failures.append("SCRIPT_MISSING_OR_STATIC_CHECK_FAILED")

    report_ok = _regular_file(workspace / "output" / "report.md")
    if not report_ok:
        failures.append("REPORT_MISSING")

    schema_earned = (5.0 if checks["strict_schema"] else 0.0) + (
        10.0 if checks["exact_set"] else 0.0
    )
    criteria = [
        _criterion(
            "D1_candidate_set_schema",
            schema_earned,
            15.0,
            checks["strict_schema"] and checks["exact_set"],
            {
                "strict_schema": checks["strict_schema"],
                "exact_unique_candidate_set": checks["exact_set"],
                "missing_variants": checks["missing_variants"],
                "extra_variants": checks["extra_variants"],
            },
        ),
        _criterion(
            "D2_variant_rules_and_origin",
            35.0 * correct_count / len(expected_candidates),
            35.0,
            variant_rules_ok,
            {
                "correct_variants": checks["correct_variants"],
                "total_expected_variants": len(expected_candidates),
                "truth_derived_from": [
                    "method_note.md",
                    "pedigree.csv",
                    "gene_panel.csv",
                    "variants.csv",
                ],
            },
        ),
        _criterion(
            "D3_gene_summary_consistency",
            15.0 if summary_ok else 0.0,
            15.0,
            summary_ok,
            summary_details,
        ),
        _criterion(
            "D4_script_static_check",
            10.0 if script_ok else 0.0,
            10.0,
            script_ok,
            script_details,
        ),
        _criterion(
            "D5_report_exists",
            5.0 if report_ok else 0.0,
            5.0,
            report_ok,
            "report.md exists as a regular file" if report_ok else "report.md is missing",
        ),
    ]
    hardgates = {
        "candidate_schema_set_and_uniqueness": checks["strict_schema"] and checks["exact_set"],
        "depth_gq_af_consequence_and_inheritance": variant_rules_ok,
        "candidate_origin_summary_consistency": summary_ok,
        "all_deliverables_parseable": script_ok and report_ok,
        "script_present_and_statically_valid_without_stale_dependency": script_ok,
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
