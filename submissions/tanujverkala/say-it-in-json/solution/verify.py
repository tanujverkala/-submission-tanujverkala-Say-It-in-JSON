#!/usr/bin/env python3
"""
The one-command verifier -- now batch-safe and auto-discovering, for
running against an unknown/growing sample set instead of a hardcoded list
of 5 known entry configs.

For each auto-discovered entry config, and each environment (the hand-
curated fixtures in fixtures/env/*.json, PLUS auto-generated ones derived
from that file's own referenced_env_vars -- see pfcfg/envgen.py), this:

  1. Runs the legacy path:  expand(.pfcfg) -> resolve()
  2. Runs the JSON path:    convert(.pfcfg) -> resolve()   (same resolve())
  3. Diffs the two effective-settings maps and error/warning lists.
  4. Checks any golden fixtures (fixtures/golden/*.json) -- hand-derived,
     independent expected values -- against the legacy path's actual output.
  5. Emits a machine-readable unmigratable/warnings report.

A broken file (parse error, missing include, etc.) is caught, logged into
the report as a "fatal" entry, and does NOT stop the rest of the batch --
this is the "batch-safe" part.

Auto-generated environments are NOT persisted to disk (see pfcfg/envgen.py
docstring for why) -- run with --show-generated-envs to print exactly which
environments were generated per file, for reviewability.

Exit code 0 = everything green. Nonzero = at least one mismatch, a golden
fixture disagreement, or a fatal per-file error.

Usage:
    python3 verify.py [--root DIR] [--fixtures DIR] [--show-generated-envs]
"""
import argparse
import glob
import json
import os
import sys

from pfcfg import expand, resolve, IncludeError
from pfcfg.tokenizer import tokenize, PfcfgSyntaxError, Include
from pfcfg.envscan import extract_referenced_env_vars
from pfcfg.envgen import generate_environments
from converter import convert


def discover_entry_configs(root: str):
    """
    An 'entry config' is any .pfcfg file that is never the target of another
    file's @include/@include_once -- i.e. nothing pulls it in, so it must be
    an entry point someone runs directly. Files that fail to tokenize are
    excluded from graph-building (they'll surface as fatal errors in the
    main loop instead) but still counted as candidate entries.
    """
    all_files = set()
    for path in glob.glob(os.path.join(root, "**", "*.pfcfg"), recursive=True):
        all_files.add(os.path.normpath(path))

    included = set()
    for path in all_files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tokens = tokenize(fh.read())
        except Exception:
            continue  # let the main loop report this file's real error
        for tok in tokens:
            if isinstance(tok, Include):
                target = os.path.normpath(os.path.join(os.path.dirname(path), tok.path))
                included.add(target)

    entries = sorted(os.path.relpath(p, root) for p in all_files if p not in included)
    return entries


def load_env_fixtures(fixtures_dir: str):
    envs = {}
    for path in sorted(glob.glob(os.path.join(fixtures_dir, "env", "*.json"))):
        name = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as fh:
            envs[name] = json.load(fh)
    return envs


def load_golden_fixtures(fixtures_dir: str):
    goldens = []
    for path in sorted(glob.glob(os.path.join(fixtures_dir, "golden", "*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            goldens.append(json.load(fh))
    return goldens


def run_pair(entry: str, root: str, env: dict):
    assignments, _sources = expand(entry, root)
    legacy_adicts = [a.to_dict(root) for a in assignments]
    legacy = resolve(legacy_adicts, env)

    converted = convert(entry, root)
    json_side = resolve(converted["assignments"], env)

    return legacy, json_side, converted


def diff_effective(a: dict, b: dict):
    keys = set(a) | set(b)
    mismatches = []
    for k in sorted(keys):
        if a.get(k) != b.get(k):
            mismatches.append({"key": k, "legacy": a.get(k), "json": b.get(k)})
    return mismatches


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="starter/configs")
    ap.add_argument("--fixtures", default="fixtures")
    ap.add_argument("--report-out", default="unmigratable_report.json")
    ap.add_argument("--show-generated-envs", action="store_true",
                     help="print the auto-generated environment dicts per file")
    args = ap.parse_args()

    named_envs = load_env_fixtures(args.fixtures)
    goldens = load_golden_fixtures(args.fixtures)
    entries = discover_entry_configs(args.root)

    print(f"Auto-discovered {len(entries)} entry config(s):")
    for e in entries:
        print(f"  - {e}")
    print()

    all_green = True
    report_entries = []
    fatal_files = []

    print(f"{'ENTRY':45} {'ENV':28} RESULT")
    print("-" * 90)

    for entry in entries:
        try:
            assignments, _sources = expand(entry, args.root)
        except Exception as e:
            print(f"{entry:45} {'(could not parse)':28} FATAL: {e}")
            fatal_files.append({"file": entry, "reason": str(e)})
            report_entries.append({"file": entry, "environment": None, "key": None,
                                    "severity": "fatal", "reason": str(e)})
            all_green = False
            continue

        adicts = [a.to_dict(args.root) for a in assignments]
        ref_vars = extract_referenced_env_vars(adicts)
        generated = generate_environments(ref_vars)

        envs_to_run = dict(named_envs)  # always run the hand-curated ones too
        for i, genv in enumerate(generated):
            envs_to_run[f"auto:{i}"] = genv

        if args.show_generated_envs:
            print(f"  [{entry}] referenced vars: {ref_vars}")
            print(f"  [{entry}] generated {len(generated)} environment(s): {generated}")

        for env_name, env in envs_to_run.items():
            try:
                legacy, json_side, _converted = run_pair(entry, args.root, env)
            except Exception as e:
                print(f"{entry:45} {env_name:28} FATAL: {e}")
                report_entries.append({"file": entry, "environment": env_name, "key": None,
                                        "severity": "fatal", "reason": str(e)})
                all_green = False
                continue

            l_eff, l_err, l_warn = legacy
            j_eff, j_err, j_warn = json_side

            mismatches = diff_effective(l_eff, j_eff)
            err_mismatch = l_err != j_err
            ok = not mismatches and not err_mismatch
            status = "PASS" if ok else "FAIL"
            if not ok:
                all_green = False
            print(f"{entry:45} {env_name:28} {status}")
            if mismatches:
                for m in mismatches[:5]:
                    print(f"    MISMATCH {m['key']}: legacy={m['legacy']!r} json={m['json']!r}")
            if err_mismatch:
                print(f"    ERROR-LIST MISMATCH: legacy={l_err} json={j_err}")

            for e in l_err:
                report_entries.append({"file": entry, "environment": env_name,
                                        "key": e["key"], "severity": "error", "reason": e["reason"]})
            for w in l_warn:
                report_entries.append({"file": entry, "environment": env_name,
                                        "key": w["key"], "severity": "warning", "reason": w["reason"]})

    print()
    print("GOLDEN FIXTURES")
    print("-" * 90)
    for g in goldens:
        env = named_envs.get(g["environment"])
        if env is None:
            print(f"{g['id']:35} SKIP (env fixture '{g['environment']}' not found)")
            all_green = False
            continue
        try:
            assignments, _sources = expand(g["entry"], args.root)
        except Exception as e:
            print(f"{g['id']:35} FAIL (expand error: {e})")
            all_green = False
            continue
        adicts = [a.to_dict(args.root) for a in assignments]
        effective, errors, _warnings = resolve(adicts, env)

        problems = []
        for k, expected in g.get("assertions", {}).items():
            actual = effective.get(k)
            if actual != expected:
                problems.append(f"{k}: expected {expected!r}, got {actual!r}")
        expected_error_keys = set(g.get("expected_errors", []))
        actual_error_keys = {e["key"] for e in errors}
        if expected_error_keys and not expected_error_keys.issubset(actual_error_keys):
            problems.append(f"expected errors for {expected_error_keys}, got errors for {actual_error_keys}")

        status = "PASS" if not problems else "FAIL"
        if problems:
            all_green = False
        print(f"{g['id']:35} {status}")
        for p in problems:
            print(f"    {p}")

    seen = set()
    deduped = []
    for r in report_entries:
        sig = (r["file"], r["key"], r["reason"])
        if sig not in seen:
            seen.add(sig)
            deduped.append(r)
    with open(args.report_out, "w", encoding="utf-8") as fh:
        json.dump(deduped, fh, indent=2)

    print()
    print(f"Unmigratable/warnings report: {args.report_out} ({len(deduped)} entries, "
          f"{len(fatal_files)} file(s) could not be parsed at all)")
    print()
    print("OVERALL:", "PASS" if all_green else "FAIL")
    sys.exit(0 if all_green else 1)


if __name__ == "__main__":
    main()
