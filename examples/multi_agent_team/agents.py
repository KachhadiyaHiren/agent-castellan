"""The team: agent loop, delegation, tool execution, approvals and the timeline.

``Team`` is the only place that talks to Castellan. Every tool call, delegation and
approval goes through a ``Guard``; the model never sees a tool it is not allowed to use
without the decision being made first.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from agent_castellan import (
    ApprovalStatus,
    CastellanError,
    Decision,
    Effect,
    Grant,
    Guard,
    PermissionDenied,
    Principal,
    ToolCall,
)

from .models import (
    CallAction,
    ChatModel,
    DelegateAction,
    FinalAction,
    Message,
    parse_action,
)
from .timeline import Event
from .tools import TOOL_DOCS, ToolFn

ROLE_PROMPTS = {
    "planner": "You split a task into sub-tasks and delegate them. You have no tools of your own.",
    "researcher": "You research on the web with web.search and web.fetch.",
    "coder": "You read and write files in /workspace with fs.list, fs.read and fs.write.",
    "reviewer": "You review a pending request. Reply with a final answer that starts with "
    "APPROVE: or REJECT: followed by a short reason. You may read files with fs.read first.",
}

PROTOCOL = (
    "Reply with exactly one JSON object and nothing else: "
    '{"action":"call","tool":"<name>","args":{...}} to use a tool, '
    '{"action":"delegate","role":"<role>","tools":["<tool>",...],"task":"..."} to hand off work, '
    'or {"action":"final","text":"..."} when done. '
    "If a call is denied, do not repeat it: pick another approach or finish."
)

ModelFactory = Callable[[str], ChatModel]


@dataclass(frozen=True)
class Agent:
    """A running agent: its Castellan principal plus a display label."""

    principal: Principal

    @property
    def role(self) -> str:
        """The agent's role name."""
        return self.principal.role


def _fmt_args(args: dict[str, Any], limit: int = 30) -> str:
    parts = []
    for key, value in args.items():
        text = str(value).replace("\n", "\\n")
        parts.append(f"{key}={text if len(text) <= limit else text[: limit - 1] + '…'}")
    return " ".join(parts)


def explain(decision: Decision) -> str:
    """Say in a few words which rule, grant or budget produced a decision."""
    if decision.source == "approval":
        return f"approval of rule {decision.rule_id}"
    if decision.source == "default":
        return "no rule matched: default deny"
    if decision.source == "policy" and decision.rule_id:
        return f"rule {decision.rule_id}"
    return f"{decision.source}: {decision.reason}"


class Team:
    """Runs agents for one task and records a timeline of everything Castellan decided."""

    def __init__(
        self,
        guard: Guard,
        tools: dict[str, ToolFn],
        model_factory: ModelFactory,
        *,
        max_steps: int = 10,
    ) -> None:
        self.guard = guard
        self.timeline: list[Event] = []
        self._tools = tools
        self._model_factory = model_factory
        self._max_steps = max_steps
        self.agents: dict[str, Agent] = {}
        self.grants: dict[str, Grant] = {}
        self._root: Agent | None = None
        self._reviewer: Agent | None = None

    # -- running ----------------------------------------------------------------------------

    def run(self, task: str, *, on_behalf_of: str = "user-1") -> str:
        """Start a run: the planner (root agent) works on ``task``; return its answer."""
        self._root = Agent(self.guard.start_run("planner", on_behalf_of=on_behalf_of))
        self.agents["planner"] = self._root
        return self.run_agent(self._root, task)

    def run_agent(self, agent: Agent, task: str) -> str:
        """Run one agent's loop until it gives a final answer or runs out of steps."""
        messages = [
            Message(
                "system", f"{ROLE_PROMPTS[agent.role]}\nTools:\n{self._tool_help()}\n{PROTOCOL}"
            ),
            Message("user", task),
        ]
        model = self._model_factory(agent.role)
        for _ in range(self._max_steps):
            reply = model.complete(messages)
            messages.append(Message("assistant", reply))
            action = parse_action(reply)
            if isinstance(action, FinalAction):
                return action.text
            if isinstance(action, CallAction):
                observation = self.act(agent, action.tool, action.args)
            else:
                observation = self._delegate_action(agent, action)
            messages.append(Message("user", observation))
        return "(stopped: step limit reached)"

    # -- delegation -------------------------------------------------------------------------

    def delegate(self, parent: Agent, role: str, tools: Sequence[str]) -> Agent | None:
        """Create a child agent through Castellan; return None (and log it) if refused."""
        label = f"delegate → {role} [{', '.join(tools)}]"
        try:
            child, grant = self.guard.delegate(parent.principal, role, tools=tools)
        except PermissionDenied as exc:
            self.timeline.append(
                Event(parent.role, label, "DENY", f"delegation: {exc.decision.reason}")
            )
            return None
        except CastellanError as exc:
            self.timeline.append(Event(parent.role, label, "DENY", f"grant: {exc}"))
            return None
        self.timeline.append(Event(parent.role, label, "ALLOW", "agents.can_delegate_to"))
        agent = Agent(child)
        self.agents[role] = agent
        self.grants[role] = grant
        return agent

    def _delegate_action(self, parent: Agent, action: DelegateAction) -> str:
        child = self.delegate(parent, action.role, action.tools)
        if child is None:
            reason = self.timeline[-1].cause
            return f"DENIED: {reason}. You cannot delegate this."
        answer = self.run_agent(child, action.task)
        return f"{action.role} finished: {answer}"

    # -- tool calls -------------------------------------------------------------------------

    def act(
        self,
        agent: Agent,
        tool: str,
        args: dict[str, Any],
        *,
        chain: Sequence[Grant] = (),
        note: str = "",
    ) -> str:
        """Authorize one tool call and run it if allowed; return what the agent observes."""
        call = ToolCall(tool=tool, args=args)
        label = f"{tool} {_fmt_args(args)}{note}"
        decision = self.guard.authorize(agent.principal, call, chain=chain)
        if decision.effect is Effect.ASK:
            self.timeline.append(
                Event(agent.role, label, "ASK", f"rule {decision.rule_id}: approver role:reviewer")
            )
            if not self._review(agent, call, decision):
                return "DENIED: the reviewer rejected this call."
            decision = self.guard.authorize(agent.principal, call, chain=chain)
        self.timeline.append(
            Event(agent.role, label, decision.effect.value.upper(), explain(decision))
        )
        if decision.effect is not Effect.ALLOW:
            return f"DENIED: {decision.reason}. Do not retry; use another approach."
        return self._execute(tool, args)

    def _execute(self, tool: str, args: dict[str, Any]) -> str:
        fn = self._tools.get(tool)
        if fn is None:
            return f"error: tool {tool!r} is not implemented"
        try:
            return fn(args)
        except (OSError, ValueError) as exc:
            return f"error: {exc}"

    # -- approvals --------------------------------------------------------------------------

    def _review(self, requester: Agent, call: ToolCall, decision: Decision) -> bool:
        """Spin up the reviewer agent, let it judge the pending call, and record its verdict."""
        assert self._root is not None  # noqa: S101 - run() always sets it
        if self._reviewer is None:
            self._reviewer = self.delegate(self._root, "reviewer", ["fs.read", "fs.list"])
        reviewer = self._reviewer
        if reviewer is None or decision.approval_id is None:
            return False
        task = (
            f"The {requester.role} wants to run {call.tool} with {_fmt_args(call.args, 80)}. "
            "Decide: APPROVE or REJECT."
        )
        verdict = self.run_agent(reviewer, task).strip()
        approve = verdict.upper().startswith("APPROVE")
        # Guard.approve() does not pass the approver's role to the store, so a
        # `role:reviewer` approver would never match. Call the store directly.
        store: Any = self.guard._approvals
        status = store.resolve(
            decision.approval_id,
            reviewer.principal.agent_id,
            approve,
            approver_role=reviewer.role,
        )
        ok = status is ApprovalStatus.APPROVED
        self.timeline.append(
            Event(
                "reviewer",
                f"resolve request for {call.tool}",
                "APPROVED" if ok else "REJECTED",
                f"role:reviewer says: {verdict}",
            )
        )
        return ok

    def _tool_help(self) -> str:
        return "\n".join(f"- {name}: {TOOL_DOCS.get(name, '')}" for name in sorted(self._tools))
