# EOS reproduction note

Normalize volume and energy per atom before comparing phases. Exclude rows marked non-converged. Fit each phase with a quadratic `E(V) = E0 + a (V - V0)^2` using all converged points. Report `E0`, `V0`, and `B0 = V0 * 2a * 160.21766208` in GPa.

For pressure `P` in GPa, minimize `H(V;P) = E(V) + (P / 160.21766208) V` for each fitted phase. Scan `0–10 GPa` at no coarser than `0.01 GPa` and locate the first alpha/beta enthalpy crossing. Linear interpolation between the bracketing points is acceptable.

The old script fits total cell values without atom normalization and includes non-converged rows. Repair it or replace it; save the rerunnable implementation as `output/reproduce.py`.

