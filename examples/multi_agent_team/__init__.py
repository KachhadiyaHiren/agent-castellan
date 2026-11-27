"""A small multi-agent team (planner, researcher, coder, reviewer) governed by Castellan."""

from .agents import Team
from .models import ChatModel, OpenAICompatibleModel, ScriptedModel
from .scenarios import SCENARIOS, ScenarioResult, run_scenario

__all__ = [
    "SCENARIOS",
    "ChatModel",
    "OpenAICompatibleModel",
    "ScenarioResult",
    "ScriptedModel",
    "Team",
    "run_scenario",
]
