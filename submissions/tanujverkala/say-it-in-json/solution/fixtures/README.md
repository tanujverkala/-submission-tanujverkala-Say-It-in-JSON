# Golden fixtures — spec

## Purpose

Legacy evaluator and JSON evaluator both derive from the same `expand()` walker
(see algorithm sketch). If `expand()` has a bug, both sides inherit it
identically and the legacy-vs-JSON verifier reports a false green pass.
Golden fixtures are hand-traced, independent of both evaluators, and exist
specifically to catch that failure mode. They assert a small set of witness
keys per config x environment, not full effective-settings maps.

## Fixture format

```json
{
  "id": "<entry-slug>__<env-slug>",
  "entry": "<path under starter/configs/>",
  "environment": "<filename under env/>",
  "assertions": { "section.key": "expected value", ... },
  "expected_errors": ["<key>: <reason>", ...],
  "reasoning": "plain-text hand trace of how the expected value(s) were derived"
}
```

`reasoning` is mandatory. If it can't be written, the expected value isn't
actually known yet and the fixture shouldn't be checked in.

## Environment fixtures (env/)

| file | vars | exercises |
|---|---|---|
| empty.json | {} | pure defaults, no conditionals fire |
| ci.json | CI=true | conditional blocks, cache prefix concat |
| ci-namespaced.json | CI=true, CACHE_NAMESPACE=nightly | interpolation default override |
| production.json | PRODUCTION=true | Globex's include-level conditional |
| acme-approved.json | ACME_DEPLOY_TARGET=prod-1 | Acme's inverted-boolean conditional |
| slack-on.json | SLACK_WEBHOOK, SLACK_CHANNEL | mutually-exclusive ifdef/ifndef pair |
| vault-on.json | VAULT_ADDR | Initech's ifdef/ifndef secrets branch |
| feature-beta.json | FEATURE_BETA=1 | conditional *include*, not just conditional block |
| missing-required.json | {} | triggers REQUIRED_*-with-no-default errors |

## Coverage matrix — to hand-trace next

One row = one fixture still to write, each following the same rigor as
`golden/globex-pipeline__ci.json`.

| entry | env | witness key(s) | why this pair |
|---|---|---|---|
| customers/globex/pipeline.pfcfg | ci.json | build.retry_count | DONE — include_once dedup fork |
| customers/globex/pipeline.pfcfg | production.json | build.image, deploy.strategy | include-level conditional swaps overrides.pfcfg for on-prem.pfcfg entirely |
| customers/globex/pipeline.pfcfg | empty.json | build.parallel, cache.enabled | neither CI nor PRODUCTION fires; overrides.pfcfg path taken |
| customers/acme-corp/pipeline.pfcfg | empty.json | deploy.requires_approval | default true, unless ACME_DEPLOY_TARGET set |
| customers/acme-corp/pipeline.pfcfg | acme-approved.json | deploy.requires_approval, container.tag | ifdef flips approval to false; tag interpolation cascade with $(build.node_version) |
| customers/initech/pipeline.pfcfg | empty.json | expected_errors only | REQUIRED_SIGNING_SECRET has no default -> must error, not resolve |
| customers/initech/pipeline.pfcfg | vault-on.json | secrets.provider, signing.public_key_url | ifdef/ifndef branch + chained $(signing.key_id) reference |
| edge-cases/conditional-includes.pfcfg | empty.json | expected_errors: migration.api_endpoint | REQUIRED_API_ENDPOINT has no default |
| edge-cases/conditional-includes.pfcfg | feature-beta.json | feature.beta_enabled, build.steps | conditional include swaps which template loads, plus a plain conditional block |
| edge-cases/interpolation-cascade.pfcfg | empty.json | cascade.epsilon | 4-deep interpolation chain, non-CI branch |
| edge-cases/interpolation-cascade.pfcfg | ci.json | cascade.epsilon | same chain, CI branch overrides the final key |
| edge-cases/interpolation-cascade.pfcfg | empty.json | expected_errors: cascade.loop.a, cascade.loop.b | genuine circular reference, must error not loop |

Each row gets hand-traced and turned into a `golden/<id>.json` file before the
converter/evaluator are trusted against it — not after.
