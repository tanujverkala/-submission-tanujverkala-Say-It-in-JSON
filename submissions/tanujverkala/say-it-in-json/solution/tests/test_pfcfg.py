import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pfcfg import expand, resolve

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "starter", "configs")


def _resolve(entry, env):
    assignments, _sources = expand(entry, ROOT)
    adicts = [a.to_dict(ROOT) for a in assignments]
    return resolve(adicts, env)


def test_globex_include_once_dedup_fork():
    """The golden fixture case: plain @include must register in the
    include_once seen-set, so overrides.pfcfg's @include_once of
    defaults.pfcfg is skipped and ci-shared's retry_count=0 survives."""
    effective, errors, _warnings = _resolve("customers/globex/pipeline.pfcfg", {"CI": "true"})
    assert effective["build.retry_count"] == "0"
    assert errors == []


def test_globex_production_takes_on_prem_branch():
    effective, errors, _warnings = _resolve("customers/globex/pipeline.pfcfg", {"PRODUCTION": "true"})
    assert effective["build.image"] == "pfci/builder:enterprise-rhel8"
    assert effective["build.parallel"] == "false"  # on-prem/defaults never set true here
    assert errors == []


def test_circular_reference_detected_not_looped():
    effective, errors, _warnings = _resolve("edge-cases/interpolation-cascade.pfcfg", {})
    error_keys = {e["key"] for e in errors}
    assert "cascade.loop.a" in error_keys
    assert "cascade.loop.b" in error_keys
    assert "cascade.loop.a" not in effective
    assert "cascade.loop.b" not in effective


def test_interpolation_cascade_resolves_in_order():
    effective, errors, _warnings = _resolve("edge-cases/interpolation-cascade.pfcfg", {})
    assert effective["cascade.alpha"] == "unset"
    assert effective["cascade.beta"] == "prefix-unset-suffix"
    assert effective["cascade.epsilon"] == "local-prefix-unset-suffix-final"


def test_interpolation_cascade_ci_overrides_epsilon_only():
    effective, _errors, _warnings = _resolve("edge-cases/interpolation-cascade.pfcfg", {"CI": "true"})
    assert effective["cascade.epsilon"] == "ci-prefix-unset-suffix-final"
    assert effective["cascade.alpha"] == "unset"  # unaffected by CI


def test_acme_nested_interpolation_default():
    effective, errors, _warnings = _resolve(
        "customers/acme-corp/pipeline.pfcfg", {"GIT_SHA": "abc123"}
    )
    assert effective["container.tag"] == "20-abc123"
    assert errors == []


def test_acme_deploy_target_flips_approval():
    off, _e, _w = _resolve("customers/acme-corp/pipeline.pfcfg", {})
    on, _e, _w = _resolve("customers/acme-corp/pipeline.pfcfg", {"ACME_DEPLOY_TARGET": "prod-1"})
    assert off["deploy.requires_approval"] == "true"
    assert on["deploy.requires_approval"] == "false"
    assert on["deploy.target"] == "prod-1"


def test_initech_missing_required_secret_is_warning_not_error():
    effective, errors, warnings = _resolve("customers/initech/pipeline.pfcfg", {})
    assert effective["signing.key_material"] == ""
    assert errors == []
    assert any(w["key"] == "signing.key_material" for w in warnings)


def test_initech_chained_cross_reference():
    effective, errors, _warnings = _resolve("customers/initech/pipeline.pfcfg", {})
    assert effective["signing.public_key_url"] == "initech-default.keys.example.invalid"
    assert errors == []


def test_conditional_includes_missing_endpoint_is_warning():
    effective, errors, warnings = _resolve("edge-cases/conditional-includes.pfcfg", {})
    assert effective["migration.api_endpoint"] == ""
    assert any(w["key"] == "migration.api_endpoint" for w in warnings)
    assert errors == []


def test_container_publish_ci_flips_push():
    off, _e, _w = _resolve("customers/acme-corp/pipeline.pfcfg", {})
    on, _e, _w = _resolve("customers/acme-corp/pipeline.pfcfg", {"CI": "true"})
    assert off["container.build.push"] == "false"
    assert on["container.build.push"] == "true"


def test_circular_include_raises_clean_error_not_recursion_crash(tmp_path):
    """Regression test: a plain @include cycle (A includes B includes A)
    used to cause an unbounded-recursion crash. Must now raise IncludeError."""
    from pfcfg import IncludeError

    (tmp_path / "a.pfcfg").write_text("@include b.pfcfg\n[x]\nk = 1\n")
    (tmp_path / "b.pfcfg").write_text("@include a.pfcfg\n[y]\nk = 2\n")
    try:
        expand("a.pfcfg", str(tmp_path))
        assert False, "expected IncludeError for circular include"
    except IncludeError as e:
        assert "circular include" in str(e)


def test_diamond_include_is_not_flagged_as_a_cycle(tmp_path):
    """Two different files both including a shared, non-cyclic file must
    still work -- only a genuine cycle (a file re-appearing in its own
    active ancestor chain) should error."""
    (tmp_path / "shared.pfcfg").write_text("[s]\nk = shared\n")
    (tmp_path / "a.pfcfg").write_text("@include shared.pfcfg\n@include b.pfcfg\n[x]\nk = 1\n")
    (tmp_path / "b.pfcfg").write_text("@include shared.pfcfg\n[y]\nk = 2\n")
    assignments, _sources = expand("a.pfcfg", str(tmp_path))
    assert len(assignments) >= 3  # s.k (from a's direct include), x.k, y.k -- no crash, no error


def test_deeply_nested_includes_do_not_error_or_hang(tmp_path):
    """Jordan's stated worst case: includes stacked six deep. Synthesize a
    chain of 10 files, each including the next, to check the walker holds
    up structurally (not a performance benchmark, just a correctness check
    at a depth beyond anything in the starter sample)."""
    depth = 10
    for i in range(depth):
        content = f"[level{i}]\nk = {i}\n"
        if i > 0:
            content = f"@include level{i-1}.pfcfg\n" + content
        (tmp_path / f"level{i}.pfcfg").write_text(content)
    assignments, sources = expand(f"level{depth-1}.pfcfg", str(tmp_path))
    assert len(assignments) == depth
    assert len(sources) == depth
    effective, errors, _warnings = resolve([a.to_dict(str(tmp_path)) for a in assignments], {})
    assert errors == []
    for i in range(depth):
        assert effective[f"level{i}.k"] == str(i)
