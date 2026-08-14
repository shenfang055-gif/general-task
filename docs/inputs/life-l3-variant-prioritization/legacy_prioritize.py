import csv

# Legacy prioritization script supplied for audit and repair.
with open("inputs/variants.csv", newline="") as handle:
    rows = list(csv.DictReader(handle))

kept = [
    row for row in rows
    if row["sample_id"] == "P1"
    and float(row["gnomad_af"]) < 1.0
    and row["genotype"] == "0/1"
]

with open("output/candidates.csv", "w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=["variant_id", "gene"])
    writer.writeheader()
    writer.writerows({"variant_id": row["variant_id"], "gene": row["gene"]} for row in kept)
