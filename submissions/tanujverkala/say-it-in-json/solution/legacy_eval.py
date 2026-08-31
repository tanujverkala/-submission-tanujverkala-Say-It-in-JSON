#!/usr/bin/env python3
"""
Resolves effective settings directly from a .pfcfg entry config (walks the
include tree fresh each time) against a given environment.

Usage:
    python3 legacy_eval.py <entry.pfcfg> --env fixtures/env/ci.json [--root DIR]
"""
import argparse
import json
import sys

from pfcfg import expand, resolve, IncludeError
from pfcfg.tokenizer import PfcfgSyntaxError


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("entry", help="entry .pfcfg path, relative to --root")
    ap.add_argument("--root", default="starter/configs", help="configs root directory")
    ap.add_argument("--env", required=True, help="path to an environment fixture JSON file")
    args = ap.parse_args()

    with open(args.env, "r", encoding="utf-8") as fh:
        env = json.load(fh)

    try:
        assignments, _sources = expand(args.entry, args.root)
    except (IncludeError, PfcfgSyntaxError) as e:
        print(json.dumps({"error": f"expand failed: {e}"}), file=sys.stderr)
        sys.exit(2)

    adicts = [a.to_dict(args.root) for a in assignments]
    resolved, errors, warnings = resolve(adicts, env)
    print(json.dumps({"effective": resolved, "errors": errors, "warnings": warnings}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
