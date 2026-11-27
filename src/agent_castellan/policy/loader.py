"""YAML to Policy loader with line-numbered errors (WS1)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError

from ..errors import PolicyError
from .conditions import compile_condition
from .matching import compile_tool_matcher
from .schema import Policy


def load_policy(path: str | Path) -> Policy:
    """Load and validate a policy file.

    Args:
        path: Path of the YAML policy.

    Returns:
        The validated, immutable policy.

    Raises:
        PolicyError: The file cannot be read, is not valid YAML, or breaks the policy
            schema. The message starts with `<file>:<line>` and names the rule.
    """
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PolicyError(f"cannot read policy file: {exc}", file=str(file)) from exc
    return load_policy_text(text, source=str(file))


def load_policy_text(text: str, *, source: str = "<string>") -> Policy:
    """Load and validate a policy from YAML text.

    Args:
        text: The YAML document.
        source: Name used in error messages in place of a file name.

    Returns:
        The validated, immutable policy.

    Raises:
        PolicyError: The text is not valid YAML or breaks the policy schema.
    """
    yaml = YAML(typ="rt")
    yaml.allow_duplicate_keys = False
    try:
        root = yaml.load(text)
    except MarkedYAMLError as exc:
        mark = exc.problem_mark
        line = mark.line + 1 if mark is not None else None
        problem = exc.problem or "invalid YAML"
        raise PolicyError(problem, file=source, line=line) from exc
    if not isinstance(root, CommentedMap):
        raise PolicyError("policy document must be a mapping", file=source, line=1)

    data = _plain(root)
    rules = data.get("rules")
    rule_nodes = root.get("rules")
    if isinstance(rules, list) and isinstance(rule_nodes, CommentedSeq):
        for index, raw in enumerate(rules):
            node = rule_nodes[index]
            if isinstance(raw, dict) and isinstance(node, CommentedMap):
                if "line" in raw:
                    raise PolicyError(
                        "unknown key 'line'",
                        file=source,
                        line=node.lc.key("line")[0] + 1,
                        rule_id=_rule_id(raw),
                    )
                raw["line"] = node.lc.line + 1
    data["source"] = source
    try:
        policy = Policy.model_validate(data)
    except ValidationError as exc:
        raise _convert(exc, root, data, source) from exc
    _check_rules(policy, root)
    return policy


def _check_rules(policy: Policy, root: CommentedMap) -> None:
    nodes = root.get("rules")
    for index, rule in enumerate(policy.rules):
        node = nodes[index] if isinstance(nodes, CommentedSeq) else None
        try:
            compile_tool_matcher(rule.tools)
            if rule.when is not None:
                compile_condition(rule.when)
        except PolicyError as exc:
            line = rule.line
            if isinstance(node, CommentedMap) and "when" in node:
                line = node.lc.key("when")[0] + 1
            raise PolicyError(exc.message, file=policy.source, line=line, rule_id=rule.id) from exc


def _plain(node: Any) -> Any:  # noqa: PLR0911
    """Convert ruamel containers and scalars into plain Python values."""
    if isinstance(node, Mapping):
        return {_plain(key): _plain(value) for key, value in node.items()}
    if isinstance(node, list | tuple):
        return [_plain(item) for item in node]
    if isinstance(node, bool):
        return bool(node)
    if isinstance(node, int):
        return int(node)
    if isinstance(node, float):
        return float(node)
    if isinstance(node, str):
        return str(node)
    return node


def _rule_id(raw: Mapping[str, Any]) -> str | None:
    value = raw.get("id")
    return value if isinstance(value, str) else None


def _line_of(root: CommentedMap, loc: tuple[int | str, ...]) -> int | None:
    node: Any = root
    line: int | None = None
    for part in loc:
        if isinstance(node, CommentedMap) and part in node:
            line = node.lc.key(part)[0] + 1
            node = node[part]
        elif isinstance(node, CommentedSeq) and isinstance(part, int) and part < len(node):
            line = node.lc.item(part)[0] + 1
            node = node[part]
        else:
            break
    return line


def _convert(
    exc: ValidationError, root: CommentedMap, data: dict[str, Any], source: str
) -> PolicyError:
    error = exc.errors()[0]
    loc = tuple(error["loc"])
    if error["type"] == "extra_forbidden":
        message = f"unknown key '{loc[-1]}'"
    else:
        where = ".".join(str(part) for part in loc if part != "line")
        message = f"{where}: {error['msg']}" if where else str(error["msg"])
    rule_id = None
    if len(loc) >= 2 and loc[0] == "rules" and isinstance(loc[1], int):
        raw = data.get("rules")
        if isinstance(raw, list) and loc[1] < len(raw) and isinstance(raw[loc[1]], dict):
            rule_id = _rule_id(raw[loc[1]])
    return PolicyError(message, file=source, line=_line_of(root, loc) or 1, rule_id=rule_id)
