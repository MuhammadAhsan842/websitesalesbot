"""Portable, conservative CPU sizing; no architecture-specific instructions."""

from __future__ import annotations

import math
import os
from pathlib import Path


def available_cpus() -> int:
    """Respect affinity and Linux container quota when available."""
    count = os.cpu_count() or 1
    try:
        count = min(count, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass
    quota_files = (
        ("/sys/fs/cgroup/cpu.max", None),
        ("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "/sys/fs/cgroup/cpu/cpu.cfs_period_us"),
    )
    for quota_path, period_path in quota_files:
        try:
            if period_path is None:
                quota, period = Path(quota_path).read_text().split()
                if quota == "max":
                    continue
            else:
                quota = Path(quota_path).read_text().strip()
                period = Path(period_path).read_text().strip()
            if int(quota) > 0 and int(period) > 0:
                count = min(count, max(1, math.floor(int(quota) / int(period))))
        except (OSError, ValueError):
            continue
    return max(1, count)


def default_threads() -> int:
    # Decode is often memory-bandwidth limited. More threads are not always faster.
    return min(available_cpus(), 8)
