# Synthetic bucket-model calibration

Run the model continuously over the dated series with initial storage `18 mm`.

For each day:

1. `available = max(0, precipitation - et_factor * PET)`
2. `pre_storage = storage + available`
3. `quickflow = max(0, pre_storage - capacity)`
4. `storage = min(capacity, pre_storage)`
5. `baseflow = recession * storage`
6. `storage = storage - baseflow`
7. `simulated_flow = quickflow + baseflow`

Parameter bounds are `capacity ∈ [25, 70] mm`, `recession ∈ [0.02, 0.15] day^-1`, and `et_factor ∈ [0.3, 1.1]`.

Use the first 7 days as warm-up. Calibrate on rows 8–45 by maximizing Nash–Sutcliffe efficiency (NSE), then evaluate rows 46–70 without resetting model state. The validation report must include NSE and Kling–Gupta efficiency (KGE, using correlation, variability ratio, and bias ratio).

The provided legacy implementation has water-balance errors. Repair it or replace it and save a rerunnable implementation as `output/calibrate.py`.

