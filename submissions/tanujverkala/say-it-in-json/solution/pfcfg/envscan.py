"""
Scans an assignment list (from expand()/convert()) and reports every
environment variable name it references -- via @ifdef/@ifndef conditions,
or via ${VAR...} interpolation (including vars nested inside a default/alt
expression, e.g. the GIT_SHA inside
${ACME_RELEASE_TAG:-$(build.node_version)-${GIT_SHA:-dev}}).

$(section.key) cross-references are NOT env vars and are deliberately not
collected here -- they don't need an environment fixture, they need the
referenced key to exist.

This is what makes env auto-derivation possible: instead of a human reading
every file to guess which variables matter, the converter already tokenizes
everything, so this is a cheap side-extraction, not new parsing work.
"""
from typing import Any, Dict, List, Set

from .resolve import _parse_segments, _split_var_default


def _vars_from_value(raw: str) -> Set[str]:
    found: Set[str] = set()
    for seg in _parse_segments(raw):
        if isinstance(seg, str):
            continue
        kind, inner = seg
        if kind == "ref":
            continue  # $(...) is a cross-reference, not an env var
        var, _op, rest = _split_var_default(inner)
        found.add(var.strip())
        if rest is not None:
            found |= _vars_from_value(rest)  # nested default/alt may reference more vars
    return found


def _vars_from_condition(cond) -> Set[str]:
    if cond is None:
        return set()
    if "all" in cond:
        out: Set[str] = set()
        for c in cond["all"]:
            out |= _vars_from_condition(c)
        return out
    return {cond["var"]}


def extract_referenced_env_vars(assignments: List[Dict[str, Any]]) -> List[str]:
    found: Set[str] = set()
    for a in assignments:
        found |= _vars_from_condition(a.get("condition"))
        found |= _vars_from_value(a.get("value", ""))
    return sorted(found)
