# EchoMe Project Knowledge

EchoMe keeps two separate but cooperating domains:

- **Memory** stores user behavior, working preferences, durable habits, and historical context for AI.
- **Project Knowledge** stores versioned constraints, project artifacts, evidence, and impact relations.

Project constraints do not alter the behavior of Memory retrieval or Memory Sleep. The task-aware
project context endpoint combines both domains only when an AI explicitly asks for project context.

The current deployed application version is `1.8.0`, and the current production Alembic revision is `017`.
Repository metadata and authoritative documentation are checked together by
`scripts/check_project_truth.py`; historical version plans are not current operational guidance.

## Artifact synchronization

Project artifacts remain authoritative in their repository or issue system. EchoMe stores indexed,
immutable revisions for retrieval and provenance.

1. The client scans allowed text files and computes SHA-256 for each file.
2. `POST /api/v1/project-knowledge/artifacts/sync/check` sends only the manifest.
3. Hub returns `needed`, `unchanged`, and `remote_only` paths.
4. `POST /api/v1/project-knowledge/artifacts/sync/apply` uploads only `needed` content.
5. A changed file creates a new revision and marks the previous revision `stale`.

`remote_only` is observational. The server does not delete or hide the remote artifact automatically.

## AI workflow

For a project implementation task, AI clients should call:

1. `echome_project_context` to get relevant constraints, artifact evidence, and scoped memories.
2. `echome_project_impact` before changing requirements, APIs, architecture, code paths, or tests.
3. `echome_constraint_propose` when a durable project constraint is discovered.
4. `echome_project_index` to refresh local artifacts; use `dry_run=true` before applying.

AI-created constraints default to `proposed`. User-created constraints default to `active` in the Web
project workspace. `superseded` and `deprecated` constraints are excluded from active project context.

Semantic edits create a new constraint version, copy its evidence and graph relations, and mark the old
version `superseded`. Status confirmation and verification timestamps are governance metadata and update
the current version in place.

## Constraint lifecycle

- `proposed`: useful AI inference that is not yet a confirmed project fact.
- `active`: confirmed project constraint.
- `uncertain`: historically plausible but current evidence is insufficient.
- `superseded`: replaced by another constraint; retained for provenance.
- `deprecated`: explicitly no longer applicable.

Stability is independent of status: `invariant`, `evolving`, or `temporary`. Long inactivity alone does
not change either field.

## Context Compiler

`POST /api/v1/project-knowledge/context` is the stable HTTP entry point behind
`echome_project_context`. It independently retrieves constraints, scoped memories, and artifact chunks,
then fuses lexical, PostgreSQL FTS, BGE vector, graph, changed-path, and temporal rankings with RRF.
The response includes evidence locators, conflicts, stale warnings, unknowns, selection reasons, and a
strict token budget. `local`, `overview`, and `impact` modes share the same structured contract.

Set `shadow=true` during rollout to serve the legacy result while running the compiler in parallel. The
associated `context_runs.trace.shadow_comparison` records per-domain counts, overlap, Jaccard score, and
old/new-only IDs. Normal requests use the compiler whenever `ECHOME_CONTEXT_COMPILER_ENABLED=true`.

Artifact chunks are rebuildable. Each chunk stores its immutable artifact revision, ordinal, line
locator, content hash, token count, schema version, producer, FTS document, and optional embedding. A
project advisory lock makes concurrent or resumed backfills idempotent.

## Freshness and time

`knowledge_views` are derived summaries or mental models. Their `source_watermark` identifies the
authoritative memories, artifact revisions, constraints, and events used to produce them. Reflect uses a
prepare/submit contract: the server supplies a source fingerprint, the stronger client AI writes explicit
claims with evidence references, and the Hub rejects submission if those sources changed. A new artifact
revision marks dependent views stale and creates a pending revalidation proposal for affected constraints;
it never rewrites the old evidence.

Reflect prepare verifies that the returned context and its watermark describe the same source versions.
Submit is idempotent, the server renders the stored body only from evidence-bound claims, and the producer
label is server-owned. Existing REST v1 clients may continue creating `refresh_mode=derived` views, which
retain legacy artifact-ID freshness behavior and surface as
`freshness_contract=legacy_artifact_ids` in compiled context; new clients should use Reflect for strict
per-source freshness checks.

Context queries accept `as_of` and `valid_at`. Constraints, edges, and evidence retain observed time,
valid time, invalidation time, and source metadata. Applying an approved revalidation creates a new
constraint version, preserves copied graph/evidence provenance, and supersedes the previous version.

## Events and preflight

Project events are append-only records for issues, attempts, failures, fixes, decisions, tests, deploys,
and notes. `echome_project_event_append` records an event and typed links without silently creating an
active constraint. `echome_project_preflight` is read-only: it returns evidence-backed historical risks,
relevant invariant/process/security/compatibility requirements, stale warnings, and unknowns. It warns
but does not block edits, commits, or deployments.

## Quality and automation

The 31-case fixed quality dataset groups cases by agent-memory ability: static state recall, dynamic state
tracking, workflow knowledge, environment gotchas, and premise awareness. It also measures conflicts,
abstention, evidence precision, stale answers, sensitive path leaks, latency, and token cost. The Web
**Eval** menu exposes each ability separately and can store immutable quality snapshots.
Each ability also has its own hard case-success gate, so a strong aggregate score cannot hide one weak
memory capability.

Proposal automation requires the latest three snapshots of the same dataset version to pass every
behavior threshold. `ECHOME_PROJECT_AUTOMATION_ENABLED` defaults to `false`. Even when enabled, an
automation run only creates pending revalidation proposals and exposes Sleep candidates for a stronger
client AI to turn into the existing validated Sleep JSON plan; it never applies either plan.

## Sensitive content boundary

Hub validates secret-bearing shapes on authoritative write paths instead of trusting every MCP, CLI, or
Web client to filter correctly. Private key material, sensitive artifact paths, Bearer/JWT credentials,
provider token shapes, credential assignments, and credentials embedded in URLs are rejected without
echoing the matched value. Documented placeholders remain valid. Sensitive-looking retrieval text stays
on lexical retrieval and is not sent to the embedding provider or persisted as a Context Run. The
embedding client repeats this check at the final outbound boundary; historical rebuilds skip and report
sensitive records without deleting or rewriting them.

## Isolated acceptance

Run tests and builds from the repository root:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
cd hub && UV_CACHE_DIR=/tmp/uv-cache uv run ruff check app tests
cd hub && UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
cd web && npm run build
```

Use a Hub connected to a restored database copy for write smoke and quality snapshots:

```bash
python scripts/smoke_project_knowledge.py \
  --base-url http://127.0.0.1:20010 \
  --project-id qzhqzh/EchoMe \
  --exercise-writes

python scripts/run_context_quality_eval.py \
  --base-url http://127.0.0.1:20010 \
  --project-id qzhqzh/EchoMe \
  --snapshot-key acceptance-1

python scripts/run_quality_automation.py \
  --base-url http://127.0.0.1:20010 \
  --project-id qzhqzh/EchoMe \
  --idempotency-key acceptance-dry-run
```

The write smoke refuses the Hub URL configured in `~/.echome/config.yaml`. Chunk backfill also requires
an explicit `--apply`, a checkpoint path, and `--allow-configured-hub` when deliberately targeting that
configured Hub.

## Production rollout

1. Treat the repository's single Alembic head and `scripts/check_project_truth.py` as the expected runtime
   contract; compare it with `echome_runtime_health` before deployment.
2. Obtain separate authorization for commit/push/PR and production deployment.
3. Create and verify a PostgreSQL custom-format backup, then restore it into an isolated database.
4. Rehearse the exact current-production-to-head upgrade on the copy and compare authoritative row counts
   and hashes. Never reuse a historical migration range from an old version plan.
5. Deploy with proposal automation and Context Policy enforce disabled, then run read-only smoke.
6. Run fixed eval snapshots and inspect Context Outcomes, policy effects, source mutation violations, and
   readiness. A passing readiness report never enables enforce automatically.
