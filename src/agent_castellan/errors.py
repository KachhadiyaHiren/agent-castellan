"""Exception hierarchy for Castellan."""

from __future__ import annotations

from .models import Decision


class CastellanError(Exception):
    """Base class for every error raised by Castellan."""


class PolicyError(CastellanError):
    """A policy file is invalid; the message names the file, line and rule."""

    def __init__(
        self,
        message: str,
        *,
        file: str | None = None,
        line: int | None = None,
        rule_id: str | None = None,
    ) -> None:
        self.message = message
        self.file = file
        self.line = line
        self.rule_id = rule_id
        location = ""
        if file is not None:
            location = file if line is None else f"{file}:{line}"
        rule = f"rule '{rule_id}': " if rule_id else ""
        prefix = f"{location} " if location else ""
        super().__init__(f"{prefix}{rule}{message}")


class GrantError(CastellanError):
    """A delegation grant is invalid, widened, expired or tampered with."""


class PermissionDenied(CastellanError):  # noqa: N818
    """A tool call was denied."""

    def __init__(self, decision: Decision) -> None:
        self.decision = decision
        super().__init__(decision.reason)


class ApprovalRequired(CastellanError):  # noqa: N818
    """A tool call needs approval before it can run."""

    def __init__(self, approval_id: str, decision: Decision | None = None) -> None:
        self.approval_id = approval_id
        self.decision = decision
        super().__init__(f"approval required: {approval_id}")


class BudgetExceeded(CastellanError):  # noqa: N818
    """A run, role or agent budget has been used up."""
