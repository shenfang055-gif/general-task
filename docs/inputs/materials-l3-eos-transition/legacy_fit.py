import csv

# Legacy EOS summary supplied for audit and repair.
rows = list(csv.DictReader(open("inputs/energy_volume.csv")))
best = {}
for row in rows:
    phase = row["phase"]
    energy = float(row["total_energy_ev"])
    if phase not in best or energy < best[phase][1]:
        best[phase] = (float(row["volume_cell_a3"]), energy)

with open("output/eos_parameters.csv", "w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["phase", "V0_a3_atom", "E0_ev_atom", "B0_gpa"])
    for phase, (volume, energy) in best.items():
        writer.writerow([phase, volume, energy, 0])
