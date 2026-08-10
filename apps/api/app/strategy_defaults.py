from __future__ import annotations

from typing import Any


def cold_start_strategy() -> dict[str, Any]:
    """Return an honest persisted strategy before performance evidence exists."""
    return {
        "strategy_version": 1,
        "hook_mix": {},
        "duration_mix": {},
        "visual_mix": {},
        "exploration_rate": 0.2,
        "confidence": 0.0,
        "sample_size": 0,
        "cold_start": True,
        "evidence": "No comparable performance evidence has been collected yet.",
    }
