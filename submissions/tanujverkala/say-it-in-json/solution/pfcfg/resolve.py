"""
resolve(): takes an ordered assignment list (from expand(), or read back from
converted JSON) plus an environment dict, and produces the flat effective
settings map. Used identically by the legacy evaluator and the JSON
evaluator -- this is the one function both sides share, per the algorithm
sketch agreed with the user.

Two-phase:
  Phase A -- filter by condition, replay in order (last-write-wins).
  Phase B -- interpolate each raw value, with cycle detection and a max
             expansion-depth guard (documented assumption: depth 10).
"""
from typing import Any, Dict, List, Optional, Tuple

MAX_EXPANSION_DEPTH = 10  # documented assumption -- format-reference.md leaves this undefined


class CircularReferenceError(Exception):
    def __init__(self, key: str, chain: List[str]):
        self.key = key
        self.chain = chain
        super().__init__(f"circular reference: {' -> '.join(chain + [key])}")


class ExpansionLimitError(Exception):
    def __init__(self, key: str, limit: int):
        self.key = key
        super().__init__(f"expansion depth exceeded {limit} while resolving '{key}'")


class UnknownReferenceError(Exception):
    def __init__(self, key: str, ref: str):
        self.key = key
        self.ref = ref
        super().__init__(f"'{key}' references unknown key '{ref}'")


# ---------- condition evaluation ----------

def condition_passes(condition: Optional[Dict[str, Any]], env: Dict[str, str]) -> bool:
    if condition is None:
        return True
    if "all" in condition:
        return all(condition_passes(c, env) for c in condition["all"])
    var = condition["var"]
    is_set_nonempty = bool(env.get(var))
    if condition["type"] == "ifdef":
        return is_set_nonempty
    else:  # ifndef
        return not is_set_nonempty


# ---------- interpolation mini-parser ----------
# Handles ${VAR}, ${VAR:-default}, ${VAR:+alt}, $(section.key), with arbitrary
# nesting of ${..} / $(..) inside a default/alt expression (e.g. Acme's
# tag = ${ACME_RELEASE_TAG:-$(build.node_version)-${GIT_SHA:-dev}}).

def _find_matching(s: str, start: int, open_c: str, close_c: str) -> int:
    depth = 1
    i = start
    while i < len(s):
        if s[i] == open_c:
            depth += 1
        elif s[i] == close_c:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"unbalanced '{open_c}' starting at position {start} in: {s!r}")


def _split_var_default(inner: str) -> Tuple[str, Optional[str], Optional[str]]:
    depth_brace = depth_paren = 0
    i = 0
    while i < len(inner) - 1:
        c = inner[i]
        if c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        elif c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        elif depth_brace == 0 and depth_paren == 0 and inner[i:i + 2] in (":-", ":+"):
            return inner[:i], inner[i:i + 2], inner[i + 2:]
        i += 1
    return inner, None, None


def _parse_segments(s: str) -> List[Any]:
    """Split a raw value into literal-string and ('envexpr'|'ref', inner) segments."""
    segments: List[Any] = []
    buf: List[str] = []
    i = 0
    while i < len(s):
        if s[i] == "$" and i + 1 < len(s) and s[i + 1] == "{":
            if buf:
                segments.append("".join(buf)); buf = []
            j = _find_matching(s, i + 2, "{", "}")
            segments.append(("envexpr", s[i + 2:j]))
            i = j + 1
        elif s[i] == "$" and i + 1 < len(s) and s[i + 1] == "(":
            if buf:
                segments.append("".join(buf)); buf = []
            j = _find_matching(s, i + 2, "(", ")")
            segments.append(("ref", s[i + 2:j]))
            i = j + 1
        else:
            buf.append(s[i])
            i += 1
    if buf:
        segments.append("".join(buf))
    return segments


def interpolate(raw: str, env: Dict[str, str], lookup_ref, warn_cb, key_ctx: str) -> str:
    """
    lookup_ref(dotted_key) -> resolved string, or raises Circular/Unknown/Limit errors.
    warn_cb(key_ctx, var_name) called when a bare ${VAR} (no default) resolves
    to empty string because VAR is unset -- flagged for the migration report,
    not treated as a hard error (matches format-reference.md's literal spec:
    "${VAR}" -> value or empty string if unset).
    """
    out = []
    for seg in _parse_segments(raw):
        if isinstance(seg, str):
            out.append(seg)
            continue
        kind, inner = seg
        if kind == "ref":
            out.append(lookup_ref(inner.strip()))
        else:  # envexpr
            var, op, rest = _split_var_default(inner)
            var = var.strip()
            val = env.get(var)
            set_nonempty = bool(val)
            if op is None:
                if not set_nonempty:
                    warn_cb(key_ctx, var)
                out.append(val or "")
            elif op == ":-":
                if set_nonempty:
                    out.append(val)
                else:
                    out.append(interpolate(rest, env, lookup_ref, warn_cb, key_ctx))
            else:  # ':+'
                if set_nonempty:
                    out.append(interpolate(rest, env, lookup_ref, warn_cb, key_ctx))
                else:
                    out.append("")
    return "".join(out)


# ---------- top-level resolve ----------

def resolve(assignments: List[Dict[str, Any]], env: Dict[str, str]):
    """
    assignments: list of dicts with section, key, value, condition (already
    in the shape produced by walker.expand()/AssignmentEvent.to_dict(), or
    read back from converted JSON -- same shape either way).

    Returns (effective: Dict[str,str], errors: List[Dict], warnings: List[Dict])
    """
    running: Dict[str, str] = {}
    for a in assignments:
        if condition_passes(a["condition"], env):
            running[f"{a['section']}.{a['key']}"] = a["value"]

    resolved: Dict[str, str] = {}
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    def warn_cb(key_ctx: str, var: str):
        warnings.append({"key": key_ctx, "reason": f"env var '{var}' unset, no default -- resolved to empty string"})

    def resolve_key(k: str, visiting: Tuple[str, ...], depth: int) -> str:
        if k in resolved:
            return resolved[k]
        if k not in running:
            raise UnknownReferenceError(visiting[-1] if visiting else k, k)
        if k in visiting:
            raise CircularReferenceError(k, list(visiting))
        if depth > MAX_EXPANSION_DEPTH:
            raise ExpansionLimitError(k, MAX_EXPANSION_DEPTH)
        value = interpolate(
            running[k], env,
            lambda ref: resolve_key(ref, visiting + (k,), depth + 1),
            warn_cb, k,
        )
        resolved[k] = value
        return value

    for k in list(running.keys()):
        if k in resolved:
            continue
        try:
            resolve_key(k, tuple(), 0)
        except (CircularReferenceError, ExpansionLimitError, UnknownReferenceError) as e:
            errors.append({"key": k, "reason": str(e)})

    return resolved, errors, warnings
