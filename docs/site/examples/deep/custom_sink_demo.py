"""Extending Castellan: swap in your own AuditSink while keeping every other real component."""

from agent_castellan import AuditEntry, Decision, Guard, Principal, ToolCall
from agent_castellan.delegation.chain import ChainVerifier
from agent_castellan.guard import SystemClock
from agent_castellan.policy.engine import PolicyEngine
from agent_castellan.policy.loader import load_policy
from agent_castellan.runtime.approvals import MemoryApprovalStore
from agent_castellan.runtime.budgets import MemoryBudgetTracker


class PrintSink:
    """Any object with an `append` method that fits the AuditSink protocol will do."""

    def __init__(self) -> None:
        self.n = 0

    def append(self, principal: Principal, call: ToolCall, decision: Decision) -> AuditEntry:
        print(f"[audit] {principal.role} {call.tool} -> {decision.effect.value}")
        self.n += 1
        return AuditEntry.model_construct()  # a real sink returns the stored entry


policy = load_policy("team.yaml")
clock = SystemClock()
guard = Guard(
    decider=PolicyEngine(policy),
    grants=ChainVerifier(bytes.fromhex("11" * 32), clock),
    approvals=MemoryApprovalStore(clock),
    budgets=MemoryBudgetTracker(policy.budgets),
    audit=PrintSink(),
    clock=clock,
)
who = guard.start_run("researcher")
guard.authorize(who, ToolCall(tool="web.search", args={"q": "castles"}))
