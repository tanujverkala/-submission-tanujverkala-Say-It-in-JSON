"""
expand(): walks a .pfcfg entry config and its full include tree, producing an
ordered list of assignment events. No environment is consulted here and no
interpolation is resolved -- this is purely structural (textual macro
expansion), matching the algorithm sketch agreed with the user.

Key assumption encoded here (flagged, disputed per format-reference.md):
@include_once dedup is tracked against paths registered by ANY include
directive (plain @include included), not just prior @include_once calls.
See fixtures/golden/globex-pipeline__ci.json for the worked justification
and the fixture designed to surface this if it's wrong.
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from .tokenizer import tokenize, Include, IfDef, EndIf, Section, Assign


@dataclass
class AssignmentEvent:
    section: str
    key: str
    value: str
    condition: Optional[Dict[str, Any]]
    origin_file: str
    origin_line: int
    order: int

    def to_dict(self, root_dir: str) -> Dict[str, Any]:
        return {
            "section": self.section,
            "key": self.key,
            "value": self.value,
            "condition": self.condition,
            "origin": {
                "file": os.path.relpath(self.origin_file, root_dir),
                "line": self.origin_line,
            },
            "order": self.order,
        }


class IncludeError(Exception):
    pass


def _flatten_condition(stack: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not stack:
        return None
    if len(stack) == 1:
        return stack[0]
    return {"all": list(stack)}


def expand(entry_path: str, root_dir: str):
    """
    entry_path: path to the entry .pfcfg, relative to root_dir.
    root_dir: the configs root (e.g. starter/configs).

    Returns (assignments: List[AssignmentEvent], sources: List[str])
    sources is every file pulled in (relative to root_dir), in load order,
    including the entry file itself.
    """
    entry_abs = os.path.normpath(os.path.join(root_dir, entry_path))
    seen: set = {entry_abs}
    sources: List[str] = [os.path.relpath(entry_abs, root_dir)]
    assignments: List[AssignmentEvent] = []
    order_counter = [0]

    def walk(file_abs: str, cond_stack: List[Dict[str, Any]], active: tuple):
        if not os.path.isfile(file_abs):
            raise IncludeError(f"included file not found: {file_abs}")
        with open(file_abs, "r", encoding="utf-8") as fh:
            text = fh.read()
        tokens = tokenize(text)

        current_section: Optional[str] = None
        local_stack = cond_stack  # shared mutable stack, push/pop as we go

        for tok in tokens:
            if isinstance(tok, IfDef):
                local_stack.append(
                    {"type": "ifndef" if tok.negate else "ifdef", "var": tok.var}
                )
            elif isinstance(tok, EndIf):
                if not local_stack:
                    raise IncludeError(f"{file_abs}:{tok.line}: @endif with no matching @ifdef/@ifndef")
                local_stack.pop()
            elif isinstance(tok, Include):
                target = os.path.normpath(os.path.join(os.path.dirname(file_abs), tok.path))
                if tok.once and target in seen:
                    continue
                if target in active:
                    chain = " -> ".join(os.path.relpath(p, root_dir) for p in active + (target,))
                    raise IncludeError(
                        f"circular include detected: {chain} "
                        f"(referenced from {os.path.relpath(file_abs, root_dir)}:{tok.line})"
                    )
                seen.add(target)  # plain @include also registers -- see module docstring
                sources.append(os.path.relpath(target, root_dir))
                depth_before = len(local_stack)
                walk(target, local_stack, active + (target,))
                if len(local_stack) != depth_before:
                    raise IncludeError(
                        f"{target}: unclosed @ifdef/@ifndef leaked across include boundary "
                        f"(included from {file_abs}:{tok.line})"
                    )
            elif isinstance(tok, Section):
                current_section = tok.name
            elif isinstance(tok, Assign):
                if current_section is None:
                    raise IncludeError(f"{file_abs}:{tok.line}: key assigned before any [section]")
                assignments.append(
                    AssignmentEvent(
                        section=current_section,
                        key=tok.key,
                        value=tok.value,
                        condition=_flatten_condition(local_stack),
                        origin_file=file_abs,
                        origin_line=tok.line,
                        order=order_counter[0],
                    )
                )
                order_counter[0] += 1

    expand_stack: List[Dict[str, Any]] = []
    walk(entry_abs, expand_stack, (entry_abs,))
    if expand_stack:
        raise IncludeError(f"{entry_abs}: unclosed @ifdef/@ifndef at end of file")

    return assignments, sources
