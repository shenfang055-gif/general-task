#!/usr/bin/env python3
"""Independent oracle for materials-l1-cif-audit.

Dependencies: Python 3.9+ standard library only.  The submission is never
imported or executed.  Rerun testing belongs in a separately isolated CI job.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import re
import shlex
from collections import OrderedDict
from itertools import product
from pathlib import Path
from typing import Any


TASK_ID = "materials-l1-cif-audit"
REQUIRED_REPORT_KEYS = [
    "sample_id", "source_file", "reduced_formula", "site_count",
    "a_ang", "b_ang", "c_ang", "volume_a3", "space_group_number",
    "nearest_neighbor_a", "decoy_ignored",
]
WEIGHTS = OrderedDict([
    ("source", 10),
    ("formula_site", 10),
    ("cell", 10),
    ("volume", 10),
    ("symmetry", 10),
    ("distance", 10),
    ("decoy", 5),
    ("normalized_cif", 5),
    ("script", 5),
    ("report", 5),
])


class OracleError(Exception):
    """Expected grading error that should be reported as JSON."""


def _number(token: str) -> float:
    token = token.strip().strip("'\"")
    token = re.sub(r"(?<=\d)\([^)]*\)$", "", token)
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("non-finite CIF number")
    return value


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line, comments=True, posix=True)
    except ValueError as exc:
        raise ValueError(f"invalid CIF line: {line!r}") from exc


def parse_cif(path: Path) -> dict[str, Any]:
    """Parse the small, text CIF subset used by this task."""
    lines = path.read_text(encoding="utf-8").splitlines()
    tags: dict[str, str] = {}
    loops: list[tuple[list[str], list[list[str]]]] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#") or stripped.lower().startswith("data_"):
            i += 1
            continue
        if stripped.lower() == "loop_":
            i += 1
            names: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("_"):
                parts = _tokens(lines[i].strip())
                if not parts:
                    break
                names.append(parts[0].lower())
                i += 1
            values: list[str] = []
            while i < len(lines):
                current = lines[i].strip()
                if (not current or current.startswith("#")):
                    i += 1
                    continue
                lower = current.lower()
                if current.startswith("_") or lower == "loop_" or lower.startswith("data_"):
                    break
                values.extend(_tokens(current))
                i += 1
            if not names or len(values) % len(names):
                raise ValueError(f"malformed loop in {path.name}")
            rows = [values[j:j + len(names)] for j in range(0, len(values), len(names))]
            loops.append((names, rows))
            continue
        if stripped.startswith("_"):
            parts = _tokens(stripped)
            if len(parts) < 2:
                raise ValueError(f"missing value for CIF tag {parts[0]}")
            tags[parts[0].lower()] = parts[1]
        i += 1

    def tag(name: str) -> float:
        if name not in tags:
            raise ValueError(f"missing CIF tag {name}")
        return _number(tags[name])

    cell = {
        "a": tag("_cell_length_a"), "b": tag("_cell_length_b"),
        "c": tag("_cell_length_c"), "alpha": tag("_cell_angle_alpha"),
        "beta": tag("_cell_angle_beta"), "gamma": tag("_cell_angle_gamma"),
    }
    sites: list[dict[str, Any]] = []
    for names, rows in loops:
        if "_atom_site_fract_x" not in names:
            continue
        index = {name: names.index(name) for name in names}
        for row in rows:
            if "_atom_site_type_symbol" in index:
                species = row[index["_atom_site_type_symbol"]]
            else:
                label = row[index["_atom_site_label"]]
                match = re.match(r"([A-Z][a-z]?)", label)
                if not match:
                    raise ValueError(f"cannot infer species from {label!r}")
                species = match.group(1)
            occupancy = _number(row[index["_atom_site_occupancy"]]) if "_atom_site_occupancy" in index else 1.0
            sites.append({
                "species": species,
                "frac": tuple(_number(row[index[key]]) % 1.0 for key in (
                    "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z"
                )),
                "occupancy": occupancy,
            })
    if not sites:
        raise ValueError(f"no fractional atom sites in {path.name}")
    declared_sg = None
    for key in ("_space_group_it_number", "_symmetry_int_tables_number"):
        if key in tags:
            declared_sg = int(round(_number(tags[key])))
            break
    return {"cell": cell, "sites": sites, "declared_sg": declared_sg}


def cell_vectors(cell: dict[str, float]) -> tuple[tuple[float, float, float], ...]:
    a, b, c = cell["a"], cell["b"], cell["c"]
    alpha, beta, gamma = (math.radians(cell[k]) for k in ("alpha", "beta", "gamma"))
    sg = math.sin(gamma)
    if min(a, b, c) <= 0 or abs(sg) < 1e-12:
        raise ValueError("invalid unit cell")
    ax = (a, 0.0, 0.0)
    bx = (b * math.cos(gamma), b * sg, 0.0)
    cx0 = c * math.cos(beta)
    cx1 = c * (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / sg
    cx2_sq = c * c - cx0 * cx0 - cx1 * cx1
    if cx2_sq <= 0:
        raise ValueError("non-positive unit-cell volume")
    return ax, bx, (cx0, cx1, math.sqrt(cx2_sq))


def volume(structure: dict[str, Any]) -> float:
    a, b, c = cell_vectors(structure["cell"])
    return abs(a[0] * (b[1] * c[2] - b[2] * c[1])
               - a[1] * (b[0] * c[2] - b[2] * c[0])
               + a[2] * (b[0] * c[1] - b[1] * c[0]))


def reduced_formula(structure: dict[str, Any]) -> str:
    counts: OrderedDict[str, float] = OrderedDict()
    for site in structure["sites"]:
        counts[site["species"]] = counts.get(site["species"], 0.0) + site["occupancy"]
    rounded = [round(v) for v in counts.values()]
    if not all(abs(v - r) < 1e-8 and r > 0 for v, r in zip(counts.values(), rounded)):
        return "".join(f"{el}{value:g}" for el, value in counts.items())
    divisor = rounded[0]
    for value in rounded[1:]:
        divisor = math.gcd(divisor, value)
    return "".join(el + ("" if value // divisor == 1 else str(value // divisor))
                   for el, value in zip(counts, rounded))


def nearest_neighbor(structure: dict[str, Any]) -> float:
    vectors = cell_vectors(structure["cell"])
    sites = structure["sites"]
    best = math.inf
    for i, left in enumerate(sites):
        for j, right in enumerate(sites):
            for shift in product((-1, 0, 1), repeat=3):
                if i == j and shift == (0, 0, 0):
                    continue
                df = tuple(right["frac"][k] - left["frac"][k] + shift[k] for k in range(3))
                cart = tuple(sum(df[k] * vectors[k][axis] for k in range(3)) for axis in range(3))
                distance = math.sqrt(sum(x * x for x in cart))
                if 1e-10 < distance < best:
                    best = distance
    if not math.isfinite(best):
        raise ValueError("nearest-neighbor distance unavailable")
    return best


def infer_space_group(structure: dict[str, Any]) -> int | None:
    """Geometry/species inference for the CsCl-type fixture, independent of its tag."""
    c = structure["cell"]
    cubic = (max(abs(c[k] - c["a"]) for k in ("b", "c")) <= 1e-5
             and max(abs(c[k] - 90.0) for k in ("alpha", "beta", "gamma")) <= 1e-5)
    if not cubic or len(structure["sites"]) != 2:
        return None
    coords = sorted(tuple(round(x % 1.0, 6) for x in site["frac"]) for site in structure["sites"])
    species = {site["species"] for site in structure["sites"]}
    if coords == [(0.0, 0.0, 0.0), (0.5, 0.5, 0.5)] and len(species) == 2:
        return 221
    return None


def close(a: Any, b: float, atol: float) -> bool:
    try:
        value = float(a)
        return math.isfinite(value) and abs(value - b) <= atol
    except (TypeError, ValueError, OverflowError):
        return False


def structures_equivalent(left: dict[str, Any], right: dict[str, Any], atol: float = 1e-4) -> bool:
    for key in ("a", "b", "c", "alpha", "beta", "gamma"):
        if abs(left["cell"][key] - right["cell"][key]) > atol:
            return False
    if len(left["sites"]) != len(right["sites"]):
        return False
    unused = set(range(len(right["sites"])))
    for site in left["sites"]:
        match = None
        for j in unused:
            other = right["sites"][j]
            frac_close = all(abs(((x - y + 0.5) % 1.0) - 0.5) <= atol
                             for x, y in zip(site["frac"], other["frac"]))
            if (site["species"] == other["species"] and frac_close
                    and abs(site["occupancy"] - other["occupancy"]) <= atol):
                match = j
                break
        if match is None:
            return False
        unused.remove(match)
    return True


def load_truth(root: Path) -> dict[str, Any]:
    manifest_path = root / "inputs" / "sample_manifest.csv"
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["sample_id", "file", "condition"]:
            raise OracleError("input manifest schema is invalid")
        rows = list(reader)
    if len(rows) != 1:
        raise OracleError("input manifest must contain exactly one sample")
    entry = rows[0]
    source_name = Path(entry["file"]).name
    if source_name != entry["file"]:
        raise OracleError("unsafe source path in input manifest")
    source = parse_cif(root / "inputs" / source_name)
    inferred = infer_space_group(source)
    if inferred is None or source["declared_sg"] != inferred:
        raise OracleError("input CIF symmetry is internally inconsistent")
    decoys = []
    for candidate in sorted((root / "inputs").glob("*.cif")):
        if candidate.name != source_name:
            decoys.append(parse_cif(candidate))
    return {
        "sample_id": entry["sample_id"], "source_name": source_name,
        "source": source, "decoys": decoys,
        "formula": reduced_formula(source), "site_count": len(source["sites"]),
        "volume": volume(source), "space_group": inferred,
        "nearest": nearest_neighbor(source),
    }


def inspect_core(root: Path, truth: dict[str, Any]) -> tuple[dict[str, bool], dict[str, str]]:
    out = root / "output"
    report = json.loads((out / "structure_report.json").read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("structure_report.json must contain an object")
    missing = [key for key in REQUIRED_REPORT_KEYS if key not in report]
    if missing:
        raise ValueError(f"structure_report.json missing keys: {missing}")
    normalized = parse_cif(out / "normalized_structure.cif")
    source = truth["source"]
    checks = {
        "source": report.get("sample_id") == truth["sample_id"]
                  and report.get("source_file") == truth["source_name"],
        "formula_site": report.get("reduced_formula") == truth["formula"]
                        and type(report.get("site_count")) is int
                        and report.get("site_count") == truth["site_count"],
        "cell": all(close(report.get(f"{key}_ang"), source["cell"][key], 1e-5)
                    for key in ("a", "b", "c")),
        "volume": close(report.get("volume_a3"), truth["volume"], 1e-4),
        "symmetry": type(report.get("space_group_number")) is int
                    and report.get("space_group_number") == truth["space_group"],
        "distance": close(report.get("nearest_neighbor_a"), truth["nearest"], 1e-4),
        "decoy": report.get("decoy_ignored") is True
                 and all(not structures_equivalent(normalized, decoy) for decoy in truth["decoys"]),
        "normalized_cif": structures_equivalent(normalized, source)
                          and infer_space_group(normalized) == truth["space_group"],
    }
    details = {
        "source": f"expected {truth['sample_id']} / {truth['source_name']}",
        "formula_site": f"expected {truth['formula']}, {truth['site_count']} sites",
        "cell": "expected a=b=c=%.5f Å" % source["cell"]["a"],
        "volume": f"expected {truth['volume']:.6f} Å³",
        "symmetry": f"geometry-derived space group number {truth['space_group']}",
        "distance": f"expected nearest neighbor {truth['nearest']:.6f} Å",
        "decoy": "decoy_ignored must be true and normalized CIF must not match an unregistered CIF",
        "normalized_cif": "normalized CIF must preserve cell, species, sites, occupancy, and symmetry",
    }
    return checks, details


def script_check(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "output/analyze.py is missing"
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return False, "output/analyze.py is empty"
        tree = ast.parse(text, filename=path.name)
    except Exception as exc:
        return False, f"script is not valid UTF-8 Python: {exc}"
    if not tree.body:
        return False, "output/analyze.py has no statements"
    return True, "exists, non-empty, UTF-8, and AST-parseable; execution is deferred to isolated CI"


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
    return {"id": name, "earned": round(float(earned), 3), "max": WEIGHTS[name],
            "pass": bool(passed), "details": details}


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
        "hardgates": {"core_artifacts_parseable": {"pass": False, "details": message}},
        "failure_codes": [code],
    }


def grade(root: Path) -> dict[str, Any]:
    try:
        truth = load_truth(root)
    except Exception as exc:
        return error_result("INPUT_REFERENCE_ERROR", str(exc))
    core = [root / "output" / "structure_report.json", root / "output" / "normalized_structure.cif"]
    missing = [str(path.relative_to(root)) for path in core if not path.is_file()]
    if missing:
        return scored_failure("CORE_ARTIFACT_MISSING", f"missing core artifacts: {missing}")
    try:
        checks, details = inspect_core(root, truth)
    except Exception as exc:
        return scored_failure("CORE_ARTIFACT_INVALID", str(exc))

    script_ok, script_detail = script_check(root / "output" / "analyze.py")
    report_ok, report_detail = nonempty_utf8(root / "output" / "report.md")
    checks.update({"script": script_ok, "report": report_ok})
    details.update({"script": script_detail, "report": report_detail})
    criteria = [criterion(name, WEIGHTS[name] if checks[name] else 0, checks[name], details[name])
                for name in WEIGHTS]

    hardgates = {
        "manifest_structure_not_decoy": {
            "pass": checks["source"] and checks["decoy"],
            "details": "manifest sample/source and explicit decoy handling must both be correct",
        },
        "structure_identity_and_geometry": {
            "pass": all(checks[k] for k in ("formula_site", "cell", "volume", "symmetry", "distance", "normalized_cif")),
            "details": "formula, sites, cell, volume, symmetry, neighbor distance, and normalized structure",
        },
        "angstrom_units": {
            "pass": checks["cell"] and checks["volume"] and checks["distance"],
            "details": "reported values must agree with source CIF in Å and Å³",
        },
        "required_artifacts": {
            "pass": checks["normalized_cif"] and script_ok and report_ok,
            "details": "normalized CIF, statically valid analyze.py, and non-empty report.md; rerun is deferred to isolated CI",
        },
    }
    failure_codes = []
    code_map = {
        "manifest_structure_not_decoy": "WRONG_SOURCE_OR_DECOY",
        "structure_identity_and_geometry": "STRUCTURE_SCIENCE_MISMATCH",
        "angstrom_units": "UNIT_OR_GEOMETRY_MISMATCH",
        "required_artifacts": "REQUIRED_ARTIFACT_INVALID",
    }
    for name, gate in hardgates.items():
        if not gate["pass"]:
            failure_codes.append(code_map[name])
    return {
        "task_id": TASK_ID, "grader_status": "ok",
        "hardgate_pass": all(g["pass"] for g in hardgates.values()),
        "deterministic_score": round(sum(item["earned"] for item in criteria), 3),
        "criteria": criteria, "hardgates": hardgates, "failure_codes": failure_codes,
        "reference": {
            "sample_id": truth["sample_id"], "source_file": truth["source_name"],
            "formula": truth["formula"], "site_count": truth["site_count"],
            "volume_a3": round(truth["volume"], 8),
            "space_group_number": truth["space_group"],
            "nearest_neighbor_a": round(truth["nearest"], 8),
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
