"""
Tokenizer for .pfcfg files.

Assumption (documented, not stated in format-reference.md): comments are
recognized only when the ENTIRE trimmed line starts with '#' or ';'. Inline
comments are not supported. This is required to correctly parse values like
'${SLACK_CHANNEL:-#builds}' which contain a literal '#' mid-value -- treating
'#' as comment-to-end-of-line unconditionally would truncate that value,
which is clearly not the intent given the starter files use it as real data.
"""
import re
from dataclasses import dataclass
from typing import List, Union


class PfcfgSyntaxError(Exception):
    pass


@dataclass
class Include:
    path: str
    once: bool
    line: int


@dataclass
class IfDef:
    var: str
    negate: bool  # True for @ifndef
    line: int


@dataclass
class EndIf:
    line: int


@dataclass
class Section:
    name: str
    line: int


@dataclass
class Assign:
    key: str
    value: str
    line: int


Token = Union[Include, IfDef, EndIf, Section, Assign]

_SECTION_RE = re.compile(r"^\[([A-Za-z0-9_.]+)\]$")
_INCLUDE_RE = re.compile(r"^@include\s+(\S+)$")
_INCLUDE_ONCE_RE = re.compile(r"^@include_once\s+(\S+)$")
_IFDEF_RE = re.compile(r"^@ifdef\s+([A-Za-z_][A-Za-z0-9_]*)$")
_IFNDEF_RE = re.compile(r"^@ifndef\s+([A-Za-z_][A-Za-z0-9_]*)$")
_ENDIF_RE = re.compile(r"^@endif$")


def _parse_value(raw: str, lineno: int) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        inner = raw[1:-1]
        out = []
        i = 0
        while i < len(inner):
            c = inner[i]
            if c == "\\" and i + 1 < len(inner) and inner[i + 1] in ('"', "\\"):
                out.append(inner[i + 1])
                i += 2
            else:
                out.append(c)
                i += 1
        return "".join(out)
    return raw


def tokenize(text: str) -> List[Token]:
    tokens: List[Token] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith(";"):
            continue

        m = _INCLUDE_ONCE_RE.match(line)
        if m:
            tokens.append(Include(path=m.group(1), once=True, line=lineno))
            continue
        m = _INCLUDE_RE.match(line)
        if m:
            tokens.append(Include(path=m.group(1), once=False, line=lineno))
            continue
        m = _IFDEF_RE.match(line)
        if m:
            tokens.append(IfDef(var=m.group(1), negate=False, line=lineno))
            continue
        m = _IFNDEF_RE.match(line)
        if m:
            tokens.append(IfDef(var=m.group(1), negate=True, line=lineno))
            continue
        if _ENDIF_RE.match(line):
            tokens.append(EndIf(line=lineno))
            continue
        m = _SECTION_RE.match(line)
        if m:
            tokens.append(Section(name=m.group(1), line=lineno))
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            tokens.append(Assign(key=key, value=_parse_value(value, lineno), line=lineno))
            continue
        raise PfcfgSyntaxError(f"line {lineno}: unrecognized syntax: {raw_line!r}")

    return tokens
