# Logis harness foundation — isolated implementation

This checkout preserves the original Logis application as the product base. It is
an isolated source snapshot, not a production cutover. The running app, DSH,
models, sessions, databases and grants were not modified.

## Implemented and checked

- `rework/durable_tasks.py`: SQLite durable task/run ledger, transactional single
  claims, attempt-token fencing, 128-job admission bound, idempotency conflicts,
  three-attempt retry ceiling, priorities, dependency/artifact records, event
  cursor paging, versioned approvals, cancellation, checkpoints and recovery.
- `rework/task_worker.py`: independent dispatcher with an OS process lock and
  heartbeat. Only registered handlers execute. Lost/uncertain attempts become
  `needs_review`; they are not blindly replayed. Queued tasks survive restart.
  Output ownership is retained for uncertain work. Retryable errors must be
  established to occur before effects; arbitrary errors do not retry.
- `rework/project_files.py`: canonical Windows/Docker mapping, directory discovery,
  literal filename/content search, bounded versioned pages, explicit missing-file
  results, current-hash validation and dependency revalidation. Windows writes
  reuse the existing pinned-handle `Workspace` journal and recovery copies.
  This is recoverable writing, not a claim that every filesystem effect is atomic.
- `rework/foundation_runtime.py`: approved file jobs and explicit acceptance of a
  fully verified existing file effect after a crash. Reconciliation never rewrites
  the file. The resolver is injected by the owning app; it must enforce current
  project/grant policy. There is no arbitrary shell or generated-code executor.
- `rework/foundation_api.py`: project-scoped routes reuse the existing FastAPI
  scope dependency. Registration is optional through `create_app(foundation=...)`;
  it is not enabled in the current live launcher.
- Original `server.py` and `foundation.js`: additive integration in the original
  Tasks view, retaining Logis navigation/cards. Users can submit background reads,
  review exact proposed write content, approve, cancel and inspect recovery
  evidence. The existing task board and other views remain in place.
- Shared agent tools: `workspace_list`, `workspace_search`, paged `workspace_read`
  use the existing approved partition and grants. They do not infer new access.
- Existing streaming provider: cancellation closes the active HTTP socket and
  rejects late results. Socket disconnection is tested against a real local HTTP
  fixture. Resident-model compute cessation is **not** proven by this test; the
  existing slot check still prevents a new request while the provider reports busy.
- `rework/context_guard.py`: full serialized messages/tools accounting through an
  injected tokenizer, output reserve, original-context archival, preserved
  system/developer messages, required-anchor validation and a persisted two-attempt
  compaction ceiling. `canonical_context.py` now adopts it in actual canonical
  chat/build calls. Large prompts use the configured provider's template/tokenizer
  metadata endpoints; smaller prompts can use a conservative byte ceiling.
  Template/tokenizer failure fails closed. The legacy DSH compactor is untouched.
- `rework/durable_dispatch.py`: canonical chat and standalone build dispatch now
  persists bounded invocation inputs and nonsecret principal IDs in the existing
  PostgreSQL run row. One session advisory lock coordinates dispatchers. Queued
  work resumes after restart; interrupted active work is held for review. Current
  credentials/device grants are re-resolved before execution, including file jobs.
  In-chat child builds stay within their parent's durable execution and effects
  ledger, avoiding a deadlock from enqueueing a child behind its own parent.
- Chat can be accepted while a standalone build is active in the same project.
  It queues behind the active single-slot request; status requests remain separate.
  Builds have scoped cancellation, hash-checked artifacts and late-output rejection.
- `durable-runs.js` extends the original-style task panel when canonical dispatch
  routes are present. It queues builds, exposes status/evidence and cancellation,
  retains the idempotency key after uncertain submission, and preserves edited drafts.
  It deliberately does not invent canonical backend support in the old app.

## Verification

`foundation-test-results.json` records the consolidated synthetic suite. Run with
the existing compatible Python/dependency environment using `tools/check_foundation.py`.
It starts and stops only a new disposable loopback PostgreSQL instance; it does not
fall back to a live database. Synthetic state is retained for inspection.
The latest consolidated run passed 65 tests; the JavaScript DOM interaction fixture
also passed. The temporary database was stopped after the run. The first startup
attempt stalled on inherited Windows subprocess pipe handles; the runner now uses
a log file, and only its own stalled process/test cluster were stopped.
Coverage includes process termination/restart, duplicate requests and claim races,
bounded retries, cancellation before/during effects, stale attempts, original
recovery bytes, concurrent file edits, missing paths, bounds, changed directory
cursors, changed dependency artifacts, revoked scope, authenticated API checks,
shared agent discovery and compaction limits across checkpoint replacement.
Existing extraction parser tests now target `_local_model`, their actual unit
boundary, so they do not require a live identity probe or the production lock path.

`node test_durable_ui.cjs` additionally exercises rendered component actions in a
DOM fixture: queue, uncertain-submit replay key, draft preservation and cancellation.
JavaScript syntax and Python compilation were checked. Actual browser interaction
was verified with synthetic data as detailed below; exhaustive visual regression
has not been performed. Original design
documents and the saved `Atlas-dashboard.png` were inspected; no DSH UI was copied.

## Factual feature inventory

| Capability | Original installed Logis / DSH evidence | This change |
|---|---|---|
| Chat, sessions, history | Original Logis UI/server and canonical API; DSH remains separate | Preserved; no migration or full parity claim |
| Tasks and approvals | Original task board, Inbox, scoped candidate writes | Adds durable file-work lifecycle and evidence |
| Background execution | Logis in-memory `WorkQueue`, durable run records; original LangGraph checkpoints | Canonical chat and standalone builds now use durable PostgreSQL dispatch; file jobs use the durable SQLite ledger; vision remains on its existing path |
| Files | Original file tools, imported revisions, approved Windows workspace adapter | Adds shared discovery, pages, hashes and artifact dependencies |
| Memory | Canonical PostgreSQL, explicit memory/Hindsight adapters already present | No changes or automatic capture |
| MCP, plugins, teams, workflows | DSH 0.2.1-rc.2 installed, MIT package; original Logis has bounded MCP and LangGraph adapters | DSH is untouched; no verified teams/plugins/workflow parity |
| UI | Original `chat.html`, `workspace.js`, styles and OS-style navigation | Additive task panel; no DSH reskin |
| Image generation / voice | Future/deferred requirements | Not installed or enabled |

## Live integration facts and remaining work

Live original source:
`C:\Users\LOGIS_USER\Documents\Codex\2026-10-22\us\outputs\Local AI\Builder`.
The running backend is `rework\serve_candidate.py`, port 8092. DSH remains in
`logis-dsh-web` on loopback 3080; its project bind is `C:\AI\Projects` → `/workspace`.

Read-only inspection found 40 canonical projects, of which 36 are archived. The
authenticated live API also returns 40. A preliminary comparison of all API
projects against only unarchived DB projects was corrected; there is no established
wrong-database mismatch. No active canonical runs were observed at inspection.
Only five canonical IDs have corresponding original `Projects/<id>/files` roots;
the current four unarchived projects do not. Each of those four does have its
existing SHA-256-named partition under `Documents/LogisWorkspaces`. The IDs are
synthetic test/acceptance records; they do not establish the user's intended active
project. The candidate's explicit workspace grant file is absent. These facts do
not authorize guessing, reactivating archived projects or migrating roots.

Before live installation, establish the intended current project-root mapping and
its existing authorization, inject that resolver into the candidate foundation,
and integrate the desired original UI with the canonical backend. Recheck active
work immediately before any restart. Current production processes were not stopped.

Remaining implementation/integration: broad DSH agents/plugins/workflow capability
parity, full original-UI/canonical-backend compatibility and live provider slot-release
verification. Synthetic browser acceptance now covers the paths listed below. Vision and optional external work paths have
not been migrated. Existing chat/build dispatch and context recovery are now wired
and tested; this still is not a completed production cutover or universal agent.

## Exact live mapping and authorization still needed

No approval is pending and no operation was denied by automatic review. These are
unperformed live integration steps, not permission errors from the test suite.

1. Identify the intended real working project ID. All four currently unarchived
   canonical IDs are test/acceptance records; do not select one or unarchive another
   on the user's behalf without confirming the intended project.
2. Confirm its exact project root and read/write operations. The existing facade
   expects `C:\Users\LOGIS_USER\AppData\Local\LogisRework\config\workspace-grant.json`
   (currently absent), containing schema version 1, root
   `C:\Users\LOGIS_USER\Documents\LogisWorkspaces`, operations
   `['create','read','edit','move']`, and `project_partitioned: true`.
   Installing that capability grant needs per-action authorization; it has not
   been created. A narrower explicit foundation resolver may be preferable.
3. After root/scope approval, bind that resolver to `Foundation`, inject it into
   `create_app`, and separately authorize source installation/restart after checking
   current active work. No launch script, service or security configuration was changed.

Observed existing test-project partitions (all relative to the root above):

| Canonical ID | Existing partition |
|---|---|
| `preview-understanding-test` | `6e7aaceff5a872291c46498fbc1f15f283eca57d116aaec84f091af8eae93e7f` |
| `preview-memory-test` | `abf7d6aae85c8c04f179ce260c99941ab0222c21b07a72070cb3ae5a2f1ea5bf` |
| `acceptance-chat-b76bd87f1d494e92bdb2a33ae84377bd` | `b62c6e6e97d5b5a58df4d9a702b97d22eff1631d144e90915355654eace2a6b4` |
| `release-acceptance-337ad74a7e384bd4acf335f7108bb864` | `3d89c9cf264e3d1fa1581d34596fc48fd2a76facac4aab11b138d2c527e1b4d9` |

Provider template/tokenizer contract reference:
[official llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
The integration tests mock these endpoints and do not establish that a live server
supports every documented version-specific behavior.

## Local Logis assistance and boundaries

### Original UI integration and browser acceptance

`create_app(..., original_ui=True)` now serves the original Logis shell at `/logis`
and an explicit static-asset allowlist. It is off by default and was not enabled
on the live service. No credential is embedded in HTML. The adapter accepts an
existing scoped bearer credential, keeps it only in memory, and requires another
login after reload. It does not create credentials or broaden project scope.

Implemented and browser-checked with `tools/preview_original_ui.py`:

| Original feature | Canonical integration |
|---|---|
| Original sidebar, cards, task board, theme and conversation layout | Preserved original source and styling |
| Existing scoped projects and history | Read and select |
| Chat and standalone builds | Durable submission, queue status and cancel |
| Task, decision, case, conference, routine, pipeline, instruction, agent-role and organization records | Create/edit through canonical API; expected-version conflict protection; saved plans do not execute themselves |
| File discovery | Exact root-relative listing and literal filename search; bounded paging |
| File reading | Current SHA-256, version-pinned next page, missing-file guidance |
| File changes | Full bounded read required for editing; explicit proposal and separate approval; committed readback |
| Background task and build evidence | Original Tasks view with checkpoint/status cards |
| Dashboard | Scoped counts; active run inventory explicitly limited to 20 current projects |
| Project settings, archive and recoverable Trash | Versioned/idempotent canonical metadata; no file moves or deletion; active work blocks archive |
| Existing paired-device session | Same-origin cookie authentication with existing CSRF rules; no new pairing/grants |
| Memory and conversation sources | Current confirmed source-backed records and bounded message pages; no model recall call |
| Activity/timeline | Paged durable outbox event projection, explicit refresh preserves loaded pages |
| Artifacts and agents | Saved build evidence, configured roles and scoped dispatcher status |
| Skills | Saved instructions and actual registered capability metadata; no health probes or grants |

The browser verified a synthetic task status/edit, completed chat response,
canceled build, successful file-read job and approved file edit. The file hash
changed from `6d8fd5578d7cd920b5155e3096dbacc38bff15c1d7ed37dd8a6ba281f8ebf885`
to `9742f3281651935f9d15e2237073547ea5aa05e1cc90cb22b531994433fb54a3`
and current content was read back. See `browser-acceptance.json` and
`original-ui-browser-proof.jpg`. The fixture never invokes a real model and has
its own temporary database, files, ledger and loopback port.

Still incomplete: canonical project creation and complete filesystem export in this
original UI; new-device pairing management; media attachments; original Inbox,
account, cost and external integration settings views; executable routines,
pipelines and agents; original task-to-artifact run binding; full conversation
edit/retry and source-backed memory editing controls. Existing paired sessions
can sign in, and new bounded text files can now be proposed and approved.
Unsupported operations report unavailable and do not report a successful mutation.
Existing non-adapted routes and the original standalone UI are preserved. The
new adapter is not a replacement for resolving the actual live project root.

At that milestone the consolidated runner covered 52 tests, including opt-in serving, asset
allowlisting, credential isolation, task conflicts and scope isolation. The
existing DOM fixture additionally checks uncertain submission keys and edited
draft preservation. These checks establish the implemented foundation, not full
DSH feature parity or production readiness.

### Additional lifecycle and view validation

`project_lifecycle.py` adds opt-in scoped project metadata endpoints and paged
conversation sources. Rename, brief/context edits, archive, Trash and restore use
expected versions, idempotency receipts and transactional events. Trash stores the
previous archive state and preserves all sources, objects and files. Context source
selection cannot reference out-of-scope or archived projects. Archived projects
reject record mutations. Project creation remains unavailable rather than silently
granting access to a new project.

Canonical file handlers now hold the same PostgreSQL project lock as lifecycle
changes across their bounded effect and recheck project availability/scope inside
that lock. Tests verify both an archived queued write produces no file and an
in-flight write commits before archive can succeed. The SQLite recovery journal
remains authoritative about uncertain file effects; no transactional claim spans
PostgreSQL and the filesystem.

The additional synthetic browser session verified renamed project metadata,
paged source messages, a saved case, projected activity events, creation of
`parity-note.txt` through separate approval, and Trash/restore with preserved
conversation history. New file SHA-256:
`37acad55978dd8f6016eb5ad4721d2928f98f27a0f23288893deee0435270f4f`.
See `original-ui-parity-proof.jpg` and the extended browser acceptance record.
The device-session path was validated through the in-process HTTPS test client
with synthetic cookies: missing CSRF is rejected and revocation denies access.
No live device session, permission or authentication configuration was changed.

No child agents were spawned. One bounded review used the existing Logis
`tool_synthesis.synthesize` and `candidate_chat.bounded_chat`, after verifying the
configured resident endpoint. Its answer failed evidence-reference validation and
was not accepted as implementation evidence. No model was downloaded, switched,
tuned or benchmarked; no GPU settings or disabled monitor were changed.

## Export and local artifact workflow milestone

The original options dialog now offers a bounded canonical-record export. One
read-only repeatable-read PostgreSQL snapshot contains messages, source text,
records, source evidence, same-project relationships and allowlisted run evidence.
The manifest names exclusions, including filesystem bytes, withdrawn sources,
provider internals and credentials. Limits are 1,000 rows per section and 2 MiB;
oversized exports fail explicitly instead of silently truncating. The API response
includes a SHA-256 header. This is not a complete filesystem backup.

File-creator cards now offer `Queue read after commit`. The dependent task waits
for the creator's committed artifact, validates its SHA-256, and pins the actual
read to that hash. Changed artifacts fail, and canceled creators remain visibly
blocked without automatic replay. The event cursor also refreshes affected waiting
dependents. This is a verified local workflow primitive, not a general workflow
designer or automatic routine scheduler.

All 52 consolidated tests passed. New tests cover bounded export rejection,
credential/scope exclusions, withdrawn sources, the dependency/read race and
canceled-creator status propagation. JavaScript syntax and the existing DOM fixture
passed. The browser export click reached a separate download approval and the
tool timed out; download completion is unconfirmed. That synthetic export is not
needed for installation, and its approval was not bypassed. No browser acceptance
claim is made for the new dependent-read button; its backend behavior is tested.

## User-selected C: staging location

The user selected `C:\AI`. Existing `C:\AI\Projects\logis-harness-next` contains
Logis integration notes and reference files, which remain unchanged. The verified
existing Docker bind maps `C:\AI\Projects` to `/workspace` in `logis-dsh-web`.
The new source staging child is `original-logis`, corresponding to
`/workspace/logis-harness-next/original-logis`; see `installation-plan.json`.
This is source staging, not a live service cutover, filesystem grant, new canonical
project or model change. The old hardcoded facade grant still targets a different
root and has not been installed or broadened.

## Inbox and local execution handoff

The original Inbox now shows project-scoped file approvals, recovery reviews and
uncommitted artifact dependencies through the existing Foundation status API.
Paging merges current task versions, removes resolved items, and rejects stale
responses after navigation. It links to existing Tasks review actions without
approving or retrying work. Empty partial pages explicitly indicate more events.
`node test_inbox_ui.cjs`, `node test_durable_ui.cjs` and the JavaScript syntax check
passed. These are focused DOM checks, not new browser acceptance or a rerun of the
52 backend checks recorded earlier.

The existing DSH API accepted and executed local session
`logis-foundation-local-8bdd6e7`. Its unchanged default was `bonsai27-local` /
`bonsai-27b-uncensored`, routing to the local host on port 8080; the catalog also
listed Bonsai 9B. No provider/model selection or permissions were changed. Durable
events proved successful file reads and a handoff-document backup write, but the
worker repeatedly explored instead of implementing. The bounded trial was
canceled through its session API; `running: false` was verified, and the original
UI file hash remained unchanged. Cloud implementation supplied the Inbox change.
This verifies submission and execution, not reliable autonomous coding takeover.
Local session history and backups are preserved outside this repository.

A second, narrower task in the same local session completed successfully:
`logis-inbox-select-error-v1`. The model read the exact target, edited the Inbox
Tasks-navigation callback to catch project-selection failures, read it back and
finished (durable edit/result/readback events 137/138/143, completed event 149).
Independent byte comparison proved exactly the requested replacement and no
changes to the other 173 staged source files. The rejected-selection regression
failed before the local edit and passed afterward; JavaScript syntax also passed.
The local model did not run tests: its preset exposes read/edit/write tools but no
terminal. Cloud oversight ran the focused checks. No sessions remained running.

The earlier broad attempt had working edit tools and no recorded tool errors;
repeated agent/directory checks and document exploration consumed its budget.
This points to task execution behavior rather than a demonstrated access failure.
Supplying a precise anchor, one file, three tool calls and explicit finish criteria
produced a real code change. This is a verified supervised local-edit workflow,
not evidence of independent planning or autonomous implementation of the system.

The next local task, `logis-search-bound-v1`, fixed `ProjectFiles.search` rejecting
exactly-limit results when later entries did not match. Bonsai made two verified
edits: remove the premature per-entry guard and reject only actual overflow after
the existing bounded page scan. Oversized-file skip reporting and overflow errors
remain intact. Independent byte verification confirmed only those two edits,
preserving Windows line endings and all 173 other staged source files. All 13
focused Windows `FileTests` passed, including the two new regressions that failed
before the fix. The earlier 52-test full-suite report was not rerun or relabeled.

This task encountered one completed automatic DSH compaction, resumed, edited and
read back the target, then ended at durable event 190. It also made an unnecessary
`list_agents` call and understated its tool count in prose; the event log, exact
file comparison and cloud-run checks remain the evidence. No teammates were
spawned. This is the second verified local implementation task, still supervised.

The third verified local implementation, `logis-continuation-version-v1`, requires
`expected_sha256` for nonzero-offset reads. Previously a caller could omit the
hash and combine pages from different file versions. The original UI and shared
agent paging flow already send the hash. First-page reads remain unchanged;
unversioned continuation requests now receive an explicit restart-at-zero error.
The regression reproduced the gap before the local edit; all 14 focused Windows
file-handling tests passed afterward. Exact comparison confirmed one intended
edit and all 173 other staged source files unchanged.

This new task used its own session `logis-file-pages-96f7152`, preserving earlier
completed session history. Durable events show exactly read/edit/read calls,
successful edit event 22, readback 27 and completed turn 33, with no extra agent
checks or compaction. No sessions remained running. This is supervised local
execution with independent cloud verification, not autonomous system ownership.

## Atomic approved-write and verification sequence

The original file editor now submits one `write_verify` command that admits a
file-write job and dependent verification-read job in the same SQLite transaction.
Queue-capacity failure or a conflicting second key rolls back both admissions.
Replays reuse both identities, including after reopening the ledger. The write
still waits for explicit approval; the read waits for its committed artifact and
checks that version. Both jobs retain the same authorization identity for the
existing dispatch-time recheck, and public responses strip that internal metadata.
Interrupted writes remain `needs_review` and do not release the dependent read.

This reduces manual follow-up: after a user approves a proposed file change, the
existing worker performs and records its verification automatically. It is a
durable two-job file workflow, not a general scheduler for autonomous Bonsai coding.
The original editor preserves the draft and idempotency key after uncertain
submission, reports both job IDs, and does not issue approval commands itself.

Local task `logis-write-verify-v1` in session `logis-write-verify-10cc153` made all
seven exact implementation edits across `durable_tasks.py`, `foundation_runtime.py`
and `canonical-ui.js`. Byte verification found no changes to the other 171 staged
source files. The session completed at event 76 and is idle. Its prose miscounted
calls; the actual event record contains 14 tool calls (one extra readback), no
spawned workers. Cloud oversight supplied tests and checked the implementation.

The consolidated disposable suite passed **59 tests**, zero failures/errors/skips.
It includes atomic rollback, concurrent idempotency, restart recovery, scoped API
approval/evidence checks and existing cancellation/file/UI-backend behavior.
The Inbox, Tasks and file-workflow DOM checks and JavaScript syntax check passed.
The new UI workflow has focused DOM acceptance, not a new browser visual check.
The synthetic PostgreSQL service was stopped; live services and data were untouched.

The next local task, `logis-terminal-dependency-v1`, closes an unstarted
queued/waiting dependent when its creator is terminally failed or canceled.
It records the upstream IDs/statuses and cancels without attempting the dependent
or undoing any effect. Repeated scans add no duplicate transition. Dependencies
whose creators need recovery review remain waiting. The regression failed before
the local edit; all 29 focused queue/file tests passed afterward. The 59-test
consolidated report above remains the preceding integration run, not a rerun.
Session `logis-dependency-stop-8a83340` completed at event 33 after exactly three
read/edit/read calls. Exact comparison verified one edit and 174 other staged
files unchanged; the worker is idle.

## Concrete activation decision and remaining adapter work

The refreshed live read-only inventory still contains 40 canonical projects,
36 archived, with only four acceptance/test projects active. No workspace grant
exists. `installation-plan.json` now records a proposal, not an installed binding:
create canonical project `logis-development` named **Logis Development**, scoped
only to `C:\AI\Projects\logis-harness-next\original-logis`, mapped by the existing
Docker bind to `/workspace/logis-harness-next/original-logis`. Private runtime
state would remain outside the mounted source tree under the user's LocalAppData.
The proposed ID does not exist and has not been granted to any credential/device.
The user must choose that new project/root pairing or identify an intended existing
canonical project/root; the prior choice of C:\AI did not resolve that identity.

The opt-in `rework/activation_adapter.py` now binds Foundation, the original UI
and shared chat file tools to one exact approved root. It requires an existing
canonical project, existing identity scope and a separately supplied exact binding
approval. No fallback to the legacy Documents grant is permitted. Its default
creates only private ledger state after validation and starts no workers/listener.
Optional startup excludes global outbox/understanding workers. See `ACTIVATION.md`
for exact effects, authorization boundaries and remaining deployment work.

Bonsai session `logis-activation-hooks-5b3f422` implemented four bounded integration
files, with nine exact edits and all other 171 staged files verified unchanged.
The cloud-authored adapter and synthetic tests passed the consolidated suite
(65 tests); the subsequent startup restriction received focused activation checks
recorded in `activation-test-results.json`. This is synthetic integration evidence,
not live activation or autonomous ownership. Original UI assets were preserved.

Live project creation, binding approval, identity scope and private-state
provisioning still require approval. A trusted loader and deployment entrypoint
must be prepared before a separately coordinated service cutover. No live project,
grant, scope, credentials, services, models or GPU settings changed.

## Rollback and installation boundary

All changes are in branch `feature/durable-foundation` of this isolated checkout.
The live originals are unchanged, so no production rollback is currently needed.
For eventual application, preserve original source versions and verify each source
hash before replacement. Keep task SQLite state and file journals on rollback;
do not delete them to hide uncertain outcomes. Never start the old launcher that
loads models as part of this model-deferred task.

## Updated local coding parity and remaining priorities

Local work now covers bounded project discovery, text-only existing-file plans,
approved dependent exact-edit execution through DSH, durable workflow inspection,
and text-only new-file proposals saved through Foundation's approved journaled
writer. Original OS-style screens remain the product UI. These capabilities are
staged and tested; they are not enabled in live services.

The next substantive gaps are: a trusted deployment entrypoint/approval loader
and coordinated activation; a configured trusted code-validation runner (generated
commands are not executed); mixed create/edit plans across the currently separate
ledgers; and broader repository planning with reliable completion criteria. DSH
teams/plugins and optional external integrations still have no full parity claim.
Image generation and voice remain deferred. General unsupervised completion of
arbitrary coding projects is not established by bounded successful tasks.

Mixed create/edit proposal admission and bounded Python/JSON syntax validation are
now implemented in the staged build; see LOCAL-WORK.md for limits and evidence.
They supersede those two earlier inventory gaps only within the stated bounds.
Semantic project test execution, JavaScript/TypeScript validation, general project
planning, full DSH parity and the approved deployment entrypoint remain unfinished.

JavaScript/TypeScript syntax checking and durable selected-file verification are
now staged using the existing bundled Node runtime, without executing source or
loading project plugins. Type checking, JSX/TSX, dependency resolution and semantic
project test execution remain unimplemented. See LOCAL-WORK.md for exact scope,
runtime assumptions, cancellation bounds and the 27-test evidence.

A trusted launch composition and read-only configuration/approval loader are now
staged in `rework/activation_entrypoint.py`; the earlier entrypoint implementation
gap is closed within the documented bearer-map/injected-provider scope. It binds
the original UI to explicitly selected managed workers and cleans up app-owned
workers on shutdown. No live launch or authorization provisioning occurred.
See ACTIVATION.md for required inputs, the exact activation boundary and evidence.

Existing-provider adapters are now staged: the canonical text/build/planner paths
use an explicitly supplied existing shared lock, and owned DSH handoffs can retain
that lock until terminal status or cancellation. The DSH RPC client accepts an
existing authenticated cookie reader without token discovery or login. Read-only
inventory confirmed current ports/private HTTPS routes and authentication-file
presence. ACTIVATION.md now records exact side-by-side versus cutover decisions,
protected-binding requirements and current limitations. No live changes occurred.

Provider admission now waits before the durable external-effect boundary, with
bounded cancellation/shutdown and scope/root/target/dependency revalidation before
submission. Known busy-timeout failures do not replay or become uncertain writes.
The local Bonsai session `logis-admission-wait-5f63ff5` completed the exact prepare
hook edit (event 43); independent comparison confirmed that edit and 227 other
staged files unchanged. Cloud review added post-wait version/scope rechecks.
`provider-adapter-test-results.json` records 33 passing focused checks; this is not
a new full-suite or live deployment claim. `ACTIVATION-CHOICE.md` captures the exact
scope/options, outstanding authentication inputs and recovered GitHub review setup.
