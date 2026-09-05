from __future__ import annotations

import math
from collections import Counter
from typing import Any

CONTENT_TYPES = {
    "selling": "problem_solution",
    "viral": "entertaining_viral",
    "informative": "educational_value",
}
DEFAULT_CONTENT_MIX = {"selling": 20, "viral": 30, "informative": 50}


def content_weights(mix: dict[str, Any] | None) -> dict[str, float]:
    source = mix or DEFAULT_CONTENT_MIX
    weights = {kind: max(0, float(source.get(key, 0))) for key, kind in CONTENT_TYPES.items()}
    total = sum(weights.values())
    if not total:
        return content_weights(DEFAULT_CONTENT_MIX)
    return {kind: weight / total for kind, weight in weights.items()}


def content_quotas(count: int, mix: dict[str, Any] | None) -> dict[str, int]:
    """Largest-remainder allocation: exact batch size, including explicit zero shares."""
    weights = content_weights(mix)
    quotas = {kind: math.floor(count * weight) for kind, weight in weights.items()}
    ordered = sorted(weights, key=lambda kind: (count * weights[kind] - quotas[kind], weights[kind]), reverse=True)
    for kind in ordered[:count - sum(quotas.values())]:
        quotas[kind] += 1
    return quotas


def research_plan(brand: dict[str, Any], count: int) -> dict[str, Any]:
    context = brand.get("project_context") or {}
    settings = brand.get("settings") or {}
    target = max(8, min(3_600, int(context.get("average_duration_seconds")
                                 or (settings.get("production") or {}).get("average_duration_seconds") or 30)))
    return {
        "average_duration_seconds": target,
        "duration_min_seconds": max(8, math.ceil(target * 0.85)),
        "duration_max_seconds": min(3_600, math.floor(target * 1.15)),
        "candidate_type_counts": content_quotas(count, context.get("content_mix") or settings.get("content_mix")),
    }


def candidate_plan_errors(items: list[dict[str, Any]], count: int, plan: dict[str, Any]) -> list[str]:
    errors = []
    if len(items) != count:
        errors.append(f"Return exactly {count} candidates, received {len(items)}")
    actual = Counter(item.get("candidate_type") for item in items)
    if any(actual[kind] != quota for kind, quota in plan["candidate_type_counts"].items()):
        errors.append(f"Candidate intent counts must be {plan['candidate_type_counts']}; received {dict(actual)}. "
                      "Rewrite the ideas to genuinely serve the assigned intent; do not just relabel them.")
    durations = [int(item.get("recommended_duration_seconds") or 30) for item in items]
    low, high, target = (plan[key] for key in ("duration_min_seconds", "duration_max_seconds", "average_duration_seconds"))
    if any(not low <= duration <= high for duration in durations):
        errors.append(f"Every candidate must be authored for {low}–{high} seconds around the user's {target}-second target")
    if durations and abs(sum(durations) / len(durations) - target) > target * 0.05:
        errors.append(f"Batch average duration must be within 5% of {target} seconds; develop enough substantive beats")
    return errors


def select_content_candidates(
    candidates: list[Any], count: int, mix: dict[str, Any] | None, existing_types: list[str],
) -> list[Any]:
    """Fill cumulative intent deficits, then rank by score within the needed intent."""
    weights = content_weights(mix)
    counts = Counter(existing_types)
    targets = content_quotas(len(existing_types) + count, mix)
    pool = sorted(candidates, key=lambda item: float(item.data.get("topic_opportunity_score") or 0), reverse=True)
    selected = []
    for _ in range(count):
        available = {item.data.get("candidate_type") or "problem_solution" for item in pool}
        eligible = [kind for kind, weight in weights.items() if weight > 0 and kind in available]
        if not eligible:
            break
        kind = max(eligible, key=lambda key: (targets[key] - counts[key], weights[key]))
        item = next(item for item in pool if (item.data.get("candidate_type") or "problem_solution") == kind)
        selected.append(item)
        pool.remove(item)
        counts[kind] += 1
    return selected
