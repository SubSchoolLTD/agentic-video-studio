from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    instruction: str
    output_key: str


AGENT_DEFINITIONS = (
    AgentDefinition(
        "producer",
        "Create a typed production brief from project policy, source, audience, objective, and budget.",
        "production_brief",
    ),
    AgentDefinition(
        "research_editor",
        "Use only supplied evidence records. Produce differentiated concepts and preserve source IDs.",
        "concepts",
    ),
    AgentDefinition(
        "script_writer",
        "Write one spoken short-form script with a hook in the first two seconds and a compliant CTA.",
        "script",
    ),
    AgentDefinition(
        "fact_policy",
        "Check every claim against source IDs. Mark support, freshness, risk, and a pass/revise/block decision.",
        "policy_decision",
    ),
    AgentDefinition(
        "director",
        "Create short scene plans with no generated text or logos and explicit aspect-ratio framing.",
        "storyboard",
    ),
    AgentDefinition(
        "qa",
        "Evaluate final media against technical, visual, content, brand, platform, and rights gates.",
        "qa_report",
    ),
)


def build_adk_agents(model: str) -> list[Any]:
    """Build the Google ADK agent network lazily so mock CI needs no credentials."""
    from google.adk.agents import LlmAgent

    return [
        LlmAgent(
            name=definition.name,
            model=model,
            instruction=definition.instruction,
            output_key=definition.output_key,
        )
        for definition in AGENT_DEFINITIONS
    ]

