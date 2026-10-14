from __future__ import annotations

import math


def median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def percentile(values, q):
    """Linear-interpolated percentile (numpy default). q in [0, 100]."""
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def p95(values):
    return percentile(values, 95)


def summarize(values):
    clean = [v for v in values if v is not None]
    return {"n": len(clean), "median": median(clean), "p95": p95(clean),
            "min": min(clean) if clean else None, "max": max(clean) if clean else None}
