"""Spotting a dev server whose memory keeps growing (a leak, or a watcher piling up modules).

A minute-by-minute memory series per process is judged on three things: it grew by at least `min_mb`, most of
its steps went up rather than down, and it is still growing at the end (a server that grew while warming up
and then levelled off is fine).
"""
from __future__ import annotations

EVERY = 60            # one sample a minute
WINDOW = 4 * 3600     # judged on the last four hours at most


def trend(samples, min_mb=500, min_minutes=30):
    """samples: [(timestamp, MB)] oldest first. Returns {growthMb, minutes, perHour, fromMb, toMb} or None."""
    if not min_mb or len(samples) < 10:
        return None
    t_end = samples[-1][0]
    samples = [s for s in samples if t_end - s[0] <= WINDOW]
    span = samples[-1][0] - samples[0][0]
    if span < min_minutes * 60:
        return None
    third = max(3, len(samples) // 3)
    low = min(mb for _, mb in samples[:third])
    end = sum(mb for _, mb in samples[-3:]) / 3
    growth = end - low
    if growth < min_mb:
        return None
    steps = [b[1] - a[1] for a, b in zip(samples, samples[1:])]
    tolerance = max(2.0, low * 0.01)
    rising = sum(1 for d in steps if d >= -tolerance) / len(steps)
    if rising < 0.7:
        return None
    recent = [s for s in samples if t_end - s[0] <= 30 * 60]
    if len(recent) < 3 or recent[-1][1] - recent[0][1] < max(10.0, growth * 0.05):
        return None   # flat for the last half hour: it settled
    minutes = round(span / 60)
    return {"growthMb": round(growth), "minutes": minutes, "perHour": round(growth / (span / 3600)),
            "fromMb": round(low), "toMb": round(end)}
