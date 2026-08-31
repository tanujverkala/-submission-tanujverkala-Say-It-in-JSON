#!/usr/bin/env python3
"""
Converts a .pfcfg entry config (plus its full include tree) into the JSON
schema at schema/pfcfg-schema.json. Structural only -- no environment is
consulted, no interpolation is resolved. That happens later, at evaluation
time, identically on both the legacy and JSON sides (see pfcfg/resolve.py).

Usage:
    python3 converter.py <entry.pfcfg relative to --root> [--root DIR] [-o out.json]
"""
import argparse
import json
import os
import sys

from pfcfg import expand, IncludeError
from pfcfg.tokenizer import PfcfgSyntaxError
from pfcfg.envscan import extract_referenced_env_vars


def convert(entry_path: str, root_dir: str) -> dict:
    assignments, sources = expand(entry_path, root_dir)
    seen_sources = []
    for s in sources:
        if s not in seen_sources:
            seen_sources.append(s)
    adicts = [a.to_dict(root_dir) for a in assignments]
    return {
        "entry": entry_path,
        "sources": seen_sources,
        "assignments": adicts,
        "referenced_env_vars": extract_referenced_env_vars(adicts),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("entry", help="entry .pfcfg path, relative to --root")
    ap.add_argument("--root", default="starter/configs", help="configs root directory")
    ap.add_argument("-o", "--output", help="output JSON path (default: stdout)")
    args = ap.parse_args()

    try:
        doc = convert(args.entry, args.root)
    except (IncludeError, PfcfgSyntaxError) as e:
        print(f"CONVERSION FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    out = json.dumps(doc, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
