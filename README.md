# Logis

Logis is a local Windows AI workspace with its original desktop-style interface,
project files, chat, reviewed memory and background tasks. This branch reconciles
the staged durable foundation with the existing canonical-backend work.

## Current implementation

- Durable task/run ledgers, dependency artifacts, idempotent submissions, bounded
  retries, checkpoints and explicit review of uncertain effects.
- Scoped Windows file reads/search/listing, current-version checks, pinned paths,
  recoverable verified writes and isolated project bindings.
- Local text-only planning, bounded discovery, exact-edit execution, new-file and
  mixed proposals, completed-work evidence and duplicate suppression.
- Original UI task flows with separate proposal acceptance and write approvals.
- Existing-provider cancellation, bounded single-slot admission and explicit
  activation composition; no automatic credentials or model changes.
- Python/JSON and JavaScript/TypeScript syntax checks without executing generated
  project code. Selected-file verification is not semantic project testing.

The existing canonical PostgreSQL backend, reviewed memory, recursive experiment,
launch scripts and GitHub checks are retained, including the existing draft history.

## Limits and deployment

Full autonomous project development, semantic project tests, JSX/TSX/typechecking,
full DSH parity and production device-auth integration remain incomplete. GitHub
checks do not autonomously improve, train or deploy Logis.

Private origins use `logis.example.invalid`, an intentionally unusable placeholder.
Configure paths and origins for the target machine before use. Existing launch
scripts can start services; they are not a portable installer. No model switch or
GPU configuration is included. Start with [FOUNDATION.md](FOUNDATION.md),
[LOCAL-WORK.md](LOCAL-WORK.md), [ACTIVATION.md](ACTIVATION.md) and
[ACTIVATION-CHOICE.md](ACTIVATION-CHOICE.md).

Not a complete installer. Machine-specific paths marked LOGIS_USER require configuration. Models, dependencies, databases, browser runtimes and private state are excluded. The running installation is separate from this development copy.

## Improvement pipeline
Issue or capability gap -> feature branch -> tests -> draft PR -> review -> explicit release. No automatic merging or deployment.

## Recursive context
rework/recursive_context.py is a bounded divide-and-summarize experiment, not the full research RLM environment or model retraining. The staged read-only adapter now adds cancellation, durable chunk progress and verified quote spans; semantic summary grounding and live activation remain outstanding. It uses at most three calls for one 32 KB file, then hands selected small files to separately approved exact-edit planning.

[RECURSIVE-INTEGRATION.md](RECURSIVE-INTEGRATION.md) describes the inspected local
installations separately from this public export, which retains the older reducer.

## Checks

The staged source passed 33 focused Windows provider/lifecycle/local-work checks
before export. See [PUBLICATION.md](PUBLICATION.md) for export verification.
Historical docs reference local evidence files deliberately excluded from GitHub;
these are not downloadable public test artifacts. Linux CI retains synthetic
canonical PostgreSQL checks and adds current UI syntax/DOM checks. Windows file
safety requires Windows and is not covered by the Linux job.
python rework/test_records.py

python rework/test_recursive_context.py

node --check app.js

node --check workspace.js


A real local three-call analysis on synthetic source has now completed without
source writes; see [RECURSIVE-DEMO.md](RECURSIVE-DEMO.md) for exact evidence and limits.
