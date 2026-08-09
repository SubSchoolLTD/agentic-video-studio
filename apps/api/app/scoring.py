from __future__ import annotations

from typing import Any

TOPIC_WEIGHTS = {
    "audience_demand": 0.20,
    "brand_relevance": 0.20,
    "freshness": 0.15,
    "novelty": 0.10,
    "evidence_quality": 0.10,
    "funnel_fit": 0.10,
    "video_fit": 0.10,
    "inverse_saturation": 0.05,
}

READINESS_WEIGHTS = {
    "hook_clarity": 0.12,
    "narrative_clarity": 0.10,
    "audience_fit": 0.10,
    "value_density": 0.10,
    "brand_consistency": 0.10,
    "visual_quality": 0.10,
    "audio_subtitles": 0.10,
    "platform_fit": 0.10,
    "factual_confidence": 0.08,
    "cta_clarity": 0.05,
    "visual_continuity": 0.05,
}


def weighted_score(breakdown: dict[str, float], weights: dict[str, float]) -> int:
    return round(sum(max(0, min(100, breakdown.get(key, 0))) * weight for key, weight in weights.items()))


def topic_score(source_count: int, brand_match: bool = True) -> dict[str, Any]:
    evidence = min(95, 50 + source_count * 12)
    breakdown = {
        "audience_demand": 82,
        "brand_relevance": 90 if brand_match else 55,
        "freshness": 78,
        "novelty": 74,
        "evidence_quality": evidence,
        "funnel_fit": 84,
        "video_fit": 88,
        "inverse_saturation": 63,
    }
    confidence = min(0.88, 0.42 + source_count * 0.11)
    return {"score": weighted_score(breakdown, TOPIC_WEIGHTS), "confidence": round(confidence, 2), "breakdown": breakdown}


def final_scores(*, source_count: int, technical_pass: bool, policy_pass: bool) -> dict[str, Any]:
    breakdown = {
        "hook_clarity": 91,
        "narrative_clarity": 88,
        "audience_fit": 92,
        "value_density": 86,
        "brand_consistency": 90,
        "visual_quality": 84 if technical_pass else 30,
        "audio_subtitles": 88 if technical_pass else 25,
        "platform_fit": 91 if technical_pass else 35,
        "factual_confidence": min(94, 62 + source_count * 9) if policy_pass else 15,
        "cta_clarity": 87,
        "visual_continuity": 85,
    }
    readiness = weighted_score(breakdown, READINESS_WEIGHTS)
    predicted = round(0.35 * 82 + 0.20 * 91 + 0.15 * 74 + 0.15 * 86 + 0.15 * 72)
    # Evidence improves editorial confidence, but a project with no measured
    # publication history must remain below the default auto-publish threshold.
    confidence = min(0.82, 0.32 + source_count * 0.07)
    return {
        "publish_readiness": readiness,
        "predicted_performance": predicted,
        "confidence": round(confidence, 2),
        "cold_start": True,
        "sample_size": 0,
        "breakdown": breakdown,
        "strongest_factors": ["Clear audience", "Immediate hook", "Platform-safe overlays"],
        "weakest_factors": ["Cold-start performance history", "Limited platform metrics"],
        "suggested_fixes": ["Collect the 24h and 7d retention windows before enabling auto-safe publishing."],
    }
