from __future__ import annotations

from apps.api.app.scoring import final_scores, topic_score


def test_topic_confidence_increases_with_evidence() -> None:
    sparse = topic_score(1)
    grounded = topic_score(4)
    assert grounded["confidence"] > sparse["confidence"]
    assert grounded["score"] >= sparse["score"]


def test_readiness_is_separate_from_predicted_performance() -> None:
    scores = final_scores(source_count=3, technical_pass=True, policy_pass=True)
    assert scores["publish_readiness"] != scores["predicted_performance"]
    assert scores["cold_start"] is True
    assert scores["sample_size"] == 0


def test_policy_failure_lowers_readiness() -> None:
    passed = final_scores(source_count=3, technical_pass=True, policy_pass=True)
    failed = final_scores(source_count=3, technical_pass=True, policy_pass=False)
    assert failed["publish_readiness"] < passed["publish_readiness"]


def test_failed_hard_gate_caps_publish_readiness() -> None:
    scores = final_scores(
        source_count=4,
        technical_pass=True,
        policy_pass=True,
        hard_gate_passed=False,
        visual_pass=False,
    )

    assert scores["publish_readiness"] <= 59
    assert scores["blocked_by_hard_gate"] is True
