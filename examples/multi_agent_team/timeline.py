"""Timeline events and their rich rendering."""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

STYLES = {
    "ALLOW": "green",
    "APPROVED": "green",
    "DENY": "bold red",
    "REJECTED": "bold red",
    "ASK": "yellow",
}


@dataclass(frozen=True)
class Event:
    """One line of the timeline: who did what, the outcome and what caused it."""

    agent: str
    action: str
    outcome: str
    cause: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "cause", clean_cause(self.cause))


def clean_cause(text: str) -> str:
    """Drop random identifiers so output is identical from run to run."""
    return re.sub(r"\s*\((?:grant|agent|appr)-[0-9a-f]+\)", "", text)


def build_table(events: Sequence[Event], title: str | None = None) -> Table:
    """Turn events into a rich table."""
    table = Table(
        title=title, box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False, expand=True
    )
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("agent", no_wrap=True)
    table.add_column("action", overflow="fold", ratio=5)
    table.add_column("decision", no_wrap=True)
    table.add_column("because", overflow="fold", ratio=5)
    for number, event in enumerate(events, start=1):
        style = STYLES.get(event.outcome, "")
        table.add_row(
            str(number),
            event.agent,
            escape(event.action),
            f"[{style}]{event.outcome}[/]" if style else event.outcome,
            escape(clean_cause(event.cause)),
        )
    return table


def render_text(events: Sequence[Event], *, width: int = 110) -> str:
    """Render the timeline as plain text with a fixed width (used by tests and the README)."""
    console = Console(file=io.StringIO(), width=width, color_system=None, force_terminal=False)
    console.print(build_table(events))
    return "\n".join(
        line.rstrip()
        for line in console.file.getvalue().rstrip().splitlines()  # type: ignore[attr-defined]
    )
