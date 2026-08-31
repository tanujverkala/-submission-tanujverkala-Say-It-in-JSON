#!/usr/bin/env python3
"""
Resolves effective settings from an already-converted JSON config (no
.pfcfg files touched, no include tree walked) against a given environment.
Uses the exact same resolve() as legacy_eval.py -- this is deliberate (see
DECISIONS.md for the caveat this implies about what the verifier can and
cannot catch).

Usage:
    python3 json_eval.py <converted.json> --env fixtures/env/ci.json
"""
import argparse
import json

from pfcfg import resolve


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("converted", help="path to a converted JSON config")
    ap.add_argument("--env", required=True, help="path to an environment fixture JSON file")
    args = ap.parse_args()

    with open(args.env, "r", encoding="utf-8") as fh:
        env = json.load(fh)
    with open(args.converted, "r", encoding="utf-8") as fh:
        doc = json.load(fh)

    resolved, errors, warnings = resolve(doc["assignments"], env)
    print(json.dumps({"effective": resolved, "errors": errors, "warnings": warnings}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
