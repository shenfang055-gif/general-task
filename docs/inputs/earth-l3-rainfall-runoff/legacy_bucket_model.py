def simulate(precip, pet, capacity, recession, et_factor, initial_storage=18.0):
    """Legacy bucket model supplied for audit and repair."""
    storage = initial_storage
    flow = []
    for p, e in zip(precip, pet):
        available = max(0.0, p + et_factor * e)
        storage = min(capacity, storage + available)
        quickflow = max(0.0, storage - capacity)
        baseflow = recession * storage
        storage -= 2 * baseflow
        flow.append(quickflow + baseflow)
    return flow
