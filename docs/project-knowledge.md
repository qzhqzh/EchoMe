# EchoMe Project Knowledge

EchoMe keeps two separate but cooperating domains:

- **Memory** stores user behavior, working preferences, durable habits, and historical context for AI.
- **Project Knowledge** stores versioned constraints, project artifacts, evidence, and impact relations.

Project constraints do not alter the behavior of Memory retrieval or Memory Sleep. The task-aware
project context endpoint combines both domains only when an AI explicitly asks for project context.

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
authoritative memories, artifact revisions, constraints, and events used to produce them. A new artifact
revision marks dependent views stale and creates a pending revalidation proposal for affected
constraints; it never rewrites the old evidence.

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

The fixed quality dataset contains 26 cases covering retrieval, historical state, supersession,
conflicts, abstention, implicit constraints, project failures, changed-path impact, and inactive-content
exclusion. The Web **Eval** menu can execute the suite and store immutable quality snapshots.

Proposal automation requires the latest three snapshots of the same dataset version to pass every
behavior threshold. `ECHOME_PROJECT_AUTOMATION_ENABLED` defaults to `false`. Even when enabled, an
automation run only creates pending revalidation proposals and exposes Sleep candidates for a stronger
client AI to turn into the existing validated Sleep JSON plan; it never applies either plan.

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

1. Obtain separate authorization for commit/push/PR and production deployment.
2. Create and verify a PostgreSQL custom-format backup; restore it into an isolated database.
3. On the copy, rehearse `010 -> 012 -> 010 -> 012` and compare authoritative row counts and hashes.
4. Deploy code with proposal automation disabled, then run Alembic upgrade to `012`.
5. Run read-only smoke against production.
6. Backfill artifact chunks in small resumable batches with a checkpoint and monitor Hub/embedding load.
7. Run three full fixed eval snapshots. Inspect the quality gate and a dry-run proposal plan.
8. Enable proposal automation only after review; keep apply in the existing explicit validation flow.
