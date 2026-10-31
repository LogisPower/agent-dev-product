# Durable local work loop — staged, opt-in

`rework/local_work_loop.py` reuses the durable task ledger for approved exact-edit
packets. `rework/local_dsh_transport.py` connects those packets to the existing DSH
session API through an authenticated RPC callback supplied by the caller. Neither
module discovers credentials, changes a model, starts a service or grants access.
The original OS-style Tasks view now has an additive Local coding tasks panel. Optional authenticated API registration does not start a worker.

The caller must supply an authorized project/root resolver, current-scope checker,
private SQLite path, and a transport bound to the same project and container cwd.
The private directory must already exist. Keep it outside the model-writable root
and use a dedicated ledger; do not reuse the Foundation file-job ledger. Protect
the state and callback with the same trusted deployment boundary as other runtime
state. The module does not install an authorization or filesystem sandbox.

## Executable sequence

1. `loop.submit(project, key, edits, principal=..., dependencies=...)` validates
   one to four existing UTF-8 files, current SHA-256 hashes, unique replacement
   anchors and output bounds. It stores the packet for explicit approval.
2. `loop.approve(project, task_id, version)` rechecks current access. The existing
   ledger reserves outputs, waits for verified predecessor artifacts and applies
   versioned approval. Duplicate identical requests return the original job even
   after its edits; conflicting requests are rejected.
3. `loop.worker.once()` processes at most one ready job. `loop.worker.start()` is
   an explicit optional background start, never called on construction. Status
   remains in SQLite independently of the model request.
4. Before the external call, the job records its stable request ID and uncertain
   submission phase. DSH gets one dedicated `logis-work-<job-id>` session and one
   prompt. Acceptance alone is not completion. The loop polls bounded session
   evidence, then reads and verifies every target's exact expected bytes.
5. Failure after submission, missing effects, timeout or uncertain process loss
   produces `needs_review`. A cancel RPC is attempted on caught errors; neither
   RPC success nor a disconnected caller proves resident model compute stopped.
   There is no automatic resubmission after uncertainty. Explicit `reconcile`
   requires provider completion and independently verified existing target files;
   it does not run the edits again.

RPC implementations must use network timeouts. The current caller helper uses
30-second RPC timeouts. The task deadline is configurable from 1 to 1,800 seconds,
default 600; a blocking callback can delay cancellation until its own timeout.
The existing DSH scheduler owns its model slot; this loop does not configure it or
coordinate unrelated inference providers.

## Limits that matter

The exact-edit primitive handles existing files, not open-ended coding plans,
shell commands or autonomous tests. The separate new-file authoring path below
uses the approved Foundation writer. The local model still
uses DSH's existing tools and OS/container rights. The new prompt and target hashes
do not revoke its broader existing mount access. Target verification cannot prove
that unrelated files were untouched; results explicitly say so. Use an isolated,
exclusively assigned checkout, retain backups and independently audit the source
manifest before accepting the change. External edits during a local write are not
protected by the deterministic Foundation adapter's compare-and-swap journal.

The loop cannot generate meaningful next tasks on its own. A trusted caller still
prepares exact packets, approves each one and performs focused semantic checks.
Dependency execution can reduce repeated manual submission, but no universal
autonomous takeover or DSH feature parity is claimed. Live deployment, protected runtime provisioning and wider workflow planning remain unfinished.

## Evidence and activation boundary

Bonsai session `logis-read-admission-8430632` completed the actual bounded
`foundation_runtime.py` edit. It rejects invalid read offsets, limits, checksums
and unversioned continuation reads before queue admission. Exact-content checks
confirmed all other 178 staged manifest files unchanged at that checkpoint.

The 23 focused file and local-loop tests passed, including approved dependent
jobs, CRLF preservation, duplicate submission after completion, stale-file and
revoked-scope rejection, queued cancellation, timeout cancellation, provider
claims without writes, persisted uncertainty and reconciliation without replay.
The final ten local-loop tests also passed after adding workspace-binding and mid-flight scope checks. The DSH bridge's project binding and session/event parsing are covered synthetically.
The earlier consolidated suite and activation evidence remain separate reports;
they were not rerun for this additive opt-in loop.

`ACTIVATION.md` remains authoritative for live requirements. Proposed canonical
identity is `logis-development`, with only the exact staged source folder as its
file root and LocalAppData private state outside it. No canonical project, identity
grant, approval record, credential or live service has been created or activated.

The actual durable handoff `d8259a7c84f4421b97bbb157475a01c9` completed in
DSH session `logis-work-d8259a7c84f4421b97bbb157475a01c9`. It corrected one stale
test-count sentence in `FOUNDATION.md`, using explicit approval, durable submission,
provider completion evidence and exact target-hash verification. The final added
project-binding and root-recheck guards were tested synthetically after this run.
Independent manifest audit then verified both local edits and all other 177
staged files unchanged. See `local-work-results.json`. The local provider did not
run tests; cloud oversight ran the focused checks. No background loop remains
started, and no live application integration is implied by this one-shot run.

## Original Tasks UI and authenticated API

The Tasks view now loads the current file and its hash, displays its contents,
and accepts one unique exact replacement plus an optional predecessor/artifact
pair. Submission saves a task for review; it never approves automatically. Cards
show exact edits, dependency state and evidence, with separate approve, cancel
and verified-reconciliation actions. An uncertain response preserves the draft
and idempotency key. Unchanged polling preserves open evidence panels. The editor
previews at most 32,768 characters; larger files require a separately prepared
bounded task. The API accepts up to four target files and eight dependencies.

`create_app(..., local_work=loop)` registers `/api/projects/{project}/local-work`
GET status/prepare and POST submit/approve/cancel/reconcile routes. It uses existing
authentication/CSRF and project scopes. Principal identity comes from authenticated
server state, never the request body. Responses exclude private root, principal,
submission fingerprint and attempt tokens. The worker's authorizer is wrapped to
recheck current credential/device write scope, project availability and the
caller's original authorization before and during execution.

Registered local execution also holds the canonical project advisory lock used
by cooperating Foundation/shared-file effects and archive operations. If another
file effect already owns it, the local attempt fails before provider submission.
This does not protect against unrelated DSH sessions or external OS edits: retain
an exclusively assigned isolated checkout and independent source-manifest audit.

The activation factory optionally accepts `local_transport=...`, requiring its
project ID and container cwd to match the exact approved binding. It constructs a
separate protected `local-work.sqlite` ledger. It does not start that worker,
including when `start_workers=True` starts the existing Foundation/chat workers.
The caller must separately coordinate local-worker ownership/start/stop. With no
transport supplied, the UI reports local work unavailable; it invents no access.

Bonsai session `logis-local-ui-hooks-bc2c3d5` made six exact integration edits in
four existing files. The other 180 staged manifest files were unchanged. Cloud
implemented the new API/panel and checked 15 focused API, activation and original
UI tests, plus the local-task and existing file-editor DOM fixtures. The tests
covered denial boundaries, scope revocation, archive, competing file effects,
exact-write completion, reconciliation and inactive defaults. This is synthetic
UI/API acceptance, not a new live browser visual acceptance or service cutover.

## Atomic named edit plans

The original Tasks panel now includes a draft plan builder. Load each current file,
prepare one exact replacement and choose **Add edit to plan**. Give the plan a
title and submit it for review. The UI supports up to eight different files and
links each step to the previous step's verified artifact automatically. Steps can
be removed before submission; uncertain replies retain the draft and request key.
Saved task cards show the plan title, step position and named predecessor details.
Each edit still requires separate explicit approval. No plan starts automatically.

The scoped `POST /api/projects/{project}/local-work/plan` route also accepts named
steps with dependencies on earlier named steps, allowing bounded branching plans.
`local_work_plan.submit_plan` validates unique files/names, rejects forward or
cyclic references, and saves every job/dependency/event in one SQLite transaction.
A later invalid or stale file, idempotency conflict, or capacity failure rolls back
the whole admission. The immutable plan contract is checked on every replay;
changing any step under the same plan key is rejected. Successful replays return
the original task IDs, including after file edits have completed. Existing saved
standalone tasks retain their prior idempotency fingerprints.

A plan permits one edit per file. Combine multiple changes in a file into one
reviewed replacement, or prepare a later plan from its new verified version.
This is explicit caller-prepared planning; it does not infer a code change from a
natural-language goal, run arbitrary commands or grant new rights. Submitted plans
are durable through the existing job ledger; unsaved browser drafts remain local
to the current page. Live activation and local-worker ownership remain separate.

Plan milestone evidence: 22 focused plan/loop/API tests and the updated local-task
DOM fixture passed. Coverage includes atomic rollback of jobs/events/dependencies,
plan contract conflicts, duplicate files, invalid graphs, old standalone replay,
ordered execution after approval and idempotent replay after completed effects.
Bonsai session `logis-plan-transaction-450ff96` implemented the eight exact
transaction/provenance/compatibility edits; the other 188 staged files were
unchanged. An intermediate duplicate import was corrected by the local session
before final exact verification; the guarded cloud cleanup did not modify it.
See `local-plan-test-results.json`. No live activation or access changes occurred.

Local reliability limitation observed in this milestone: the queued compatibility
follow-up continued revisiting already applied edits after final verification.
A staging hash guard stopped copying before any stage mutation. The owned local
session was then canceled; the session inventory confirmed it was no longer
running. Final source matched the tested code, with all other 188 staged files
unchanged. The eight intended edits were retained, but the local session is not
claimed to have finished autonomously. Prefer single immutable task packets and
stop bounded work on repeated no-progress reads; general local autonomy remains
unverified. No unrelated session or service was stopped.

## Current-state planning evidence and repeated-work stops

The Tasks panel has **Check existing work before planning**, backed by scoped
read-only `action=context`. It returns at most 20 recent project jobs and current
hashes for selected files, with explicit history truncation. Completed artifact
records are distinguished from whether those bytes still exist now. Missing or
unreadable files are explicit; no alternative filenames are guessed. Private
principals, runtime roots, raw source history and tool arguments are excluded.
The same bounded evidence is included in each immutable local execution packet,
excluding the current job. Evidence is data, never new instructions or approval.

The DSH observation adapter now supplies event sequence, model-step count and
hashed tool-call signatures. New tool activity after an old terminal event marks
execution running again. The worker stops for review when it observes more than
16 steps, more than 24 tool calls, four calls with the same signature, regressing
or malformed progress, or 180 seconds without event progress. Re-polling the same
event is deduplicated. A provider without progress metadata still has the existing
bounded overall deadline; the metadata-dependent guards cannot inspect it.

A progress stop checkpoints its reason/counts and requests cancellation. The job
remains `needs_review`, even if current files already match the intended result.
No automatic resubmission or success claim follows. Explicit reconciliation still
requires provider completion and independently verified current target hashes.
These are polling-based operational guards, not a tool-call authorization sandbox.
They cannot undo writes already made, guarantee that resident compute stopped, or
prove that unrelated files were untouched. Slow legitimate work may require
review after a conservative limit. No model/GPU configuration was changed.

Proof: 24 focused progress, local-loop and API tests and the UI fixture passed.
Tests distinguish repeated event pages from genuinely repeated calls, prove stale
historical evidence differs from current bytes, confirm completed-ID replay makes
no second provider call, and verify over-budget execution requests cancellation,
retains uncertainty and cannot be reconciled while still running. Current-state
reads are project-scoped and read-only. Progress-stop behavior is synthetic test
evidence; no deliberate live looping workload was run. Bonsai session
`logis-progress-observation-1cbc671` completed its one immutable edit using three
tool calls, and was confirmed idle. Its exact edit and all other 191 staged files
were verified. See `local-progress-test-results.json`.

## Goal-driven local proposals

The original Tasks panel can now ask a configured local text-only provider to
plan a small change from a goal and one or two selected files. This replaces
manual old/new drafting for supported small tasks. Selection is explicit, bounded
to 12 KB of UTF-8 source in total; the goal is at most 1,000 characters. The model
receives current file versions and recent completion/review evidence as data.
It has no tool interface in this planning request and cannot approve execution.

Planning is a durable `local_plan` job in the same single-dispatcher ledger. It
makes one provider call with a 90-second requested deadline and strict JSON output.
The trusted injected provider must honor that deadline and the existing
`provider_cancel` context, preserve the existing shared model-slot admission,
and have no tools or external effects. There is no new provider default, model
selection, endpoint discovery, fallback, model loading or automatic worker start.
The activation factory optionally takes `local_planner=existing_provider` only
alongside an already bound local execution transport; otherwise the UI stays
unavailable. A supplied callback that ignores its contract cannot be forcibly
bounded by this Python wrapper. The smoke test used the existing cancellable
stream transport, shared inference lock, verified identity and idle-slot check.

The parser rejects extra/duplicate JSON fields, unselected paths, ambiguous or
missing anchors, repeated files, forward dependencies and oversized responses.
Expected hashes are attached from server-read snapshots, never trusted from the
model. Versions and current authorization are checked before and after inference.
Malformed, stale or uncertain outputs are not repaired/retried automatically.
They remain available for review; no source files or execution tasks are created.

A completed proposal is not completed coding work. The user reviews its exact
steps, chooses **Create review tasks from proposal**, then approves each saved edit
separately. Acceptance uses the atomic plan builder and rechecks current versions.
Repeat acceptance returns the original tasks, including after execution; repeat
planning submissions return the original job without a second inference request.
Proposal cancellation uses the existing durable cancellation path. Unsaved goals
and keys survive an uncertain response within the current page, not page reloads.

Evidence: 22 focused planner/API/activation tests and the UI fixture passed,
including goal -> proposal -> separate acceptance -> explicit approval -> verified
file effect, repeated requests with no duplicate inference/execution, stale
acceptance rollback, unselected output rejection, cancellation and revocation.
One actual existing local-model request also produced the exact `Hello` to
`Welcome` proposal for a temporary synthetic Python file. Its durable job was
`4342c92b5e4849bc94e77317de5acc21`; source bytes remained unchanged. The verified
resident endpoint identified itself as `bonsai-27b-uncensored`; no model selection,
configuration, downloads or GPU settings changed. No proposal was executed live.
Bonsai session `logis-planner-hooks-384d2d1` supplied three exact API integration
edits, with all other 195 staged files verified unchanged, and finished idle.
It used additional internal task bookkeeping; source scope stayed bounded.
See `local-planner-test-results.json`.

Remaining limits: caller-selected files, small exact replacements, strict output
format and human semantic review. No autonomous repository discovery, arbitrary
shell/test execution, automatic approval or broad unsupervised coding is claimed.
Live project binding, scopes, protected state, local-provider wiring and coordinated
service/worker activation remain unperformed and separately approved work.

## Durable proposal workflow status

The original proposal card now has **Inspect proposal workflow**. The scoped
read-only `action=workflow&task=<proposal-id>` query links the persisted proposal
to the exact review tasks created from it, using the same deterministic plan ID
as acceptance. It reports planning, proposal-ready, approval, execution, review,
cancellation, failure or recorded completion without starting inference or retrying
anything. Private principal/root/token fields remain excluded. Status is readable
after reopening the runtime even when no planner callback is connected.

This is recorded workflow/artifact evidence, not a new assertion that the file
bytes have remained unchanged forever; current-file inspection remains separate.
There is no provider polling or source write in the status endpoint. Each edit
still needs explicit approval, and uncertain execution still needs explicit
reconciliation against provider completion and current exact file hashes.

### Existing-model end-to-end demonstration

Seven focused cases passed: six synthetic workflow/plan regressions and one
model-backed end-to-end workflow through the authenticated in-process API. The
original UI DOM fixture also passed; this was not a new visual browser test.

The demonstration created only a new disposable fixture under the existing bind:
`C:\AI\Projects\logis-harness-next\synthetic-flow-f277cddb3c`, containing
`greeting.py`. A canonical fixture project existed only in the disposable test
PostgreSQL cluster, which was stopped afterward. No live project, grant,
credential or service configuration was created or changed.

The existing resident model (`bonsai-27b-uncensored`, unchanged) proposed changing
`Hello` to `Welcome`. The API saved the exact review task and proved it would not
execute before explicit approval. One approved Bonsai edit submission produced
the expected file. The test then deliberately dropped its completion notification,
so the ledger retained `needs_review`. The runtime was closed and reconstructed
from the saved SQLite file; read-only workflow status still worked with no planner
callback connected. Explicit reconciliation confirmed provider completion and
exact source bytes without rewriting the file (mtime unchanged). Replaying both
the original planning request and proposal acceptance produced no additional
planning call or edit submission.

Evidence is in `local-workflow-demo.json` and `workflow-e2e-test-results.json`:
proposal `329e956d27f3423eb5f02291caa29d22`, edit
`fcf7e5a307764e22884bab1903da82a5`, dedicated DSH session
`logis-work-fcf7e5a307764e22884bab1903da82a5` (confirmed idle).
The final file was exactly `greeting = 'Welcome'` with a newline; no other fixture
files were created. Counts were one planning request and one edit submission.
A DSH edit submission may itself use several internal model/tool steps; these
counts do not imply only one total inference call. Fault injection and runtime
reconstruction were deliberate test mechanisms, not an observed network failure
or a machine reboot. The fixture and private test evidence were retained.

Bonsai supplied the workflow API/UI hooks, but revisited its UI edit. Exact source
verification caught the temporary mismatch; its owned session was canceled and
confirmed idle. The local session restored the requested lines before the guarded
cleanup could run, so cleanup made no write. Final source matched the reviewed
packet (allowing inspected source line-ending normalization). This still limits
claims of general unattended coding, despite the successful protected workflow.
Live activation and broader repository planning remain separate pending work.

### Bounded discovery into durable planning

The original Tasks panel now offers a literal filename/content query and optional
project-relative directory. Discovery is a saved read-only worker job, independent
of model availability. It visits at most eight directories, 200 returned entries
and 24 text files of at most 12 KB each; each directory uses one 50-entry page.
The existing listing adapter may enumerate up to 5,000 names to produce a sorted
page. Hidden/control folders, links, node_modules and caches stay excluded.
Truncation and unavailable/oversized files are explicit; this is not a complete
repository index. Narrowing the directory/query creates a distinct request.
Repeating the identical UI request returns its existing snapshot.

Select one or two discovered files and submit a goal to the existing local text
planner. The transition preserves discovery provenance, checks current root and
file hashes, and blocks unfinished or uncertain work on selected files. Files
matching a completed artifact require an explicit new-goal choice. Repeating the
same discovery-to-goal transition returns the original proposal even after its
edits complete. This is request/evidence-based suppression, not semantic proof
that two differently worded goals are equivalent. Direct selected-file planning
continues to support its existing explicit workflow.

Proposals still require separate review-task creation and per-edit approval.
Discovery does not grant access, start workers, configure providers or change
source. Saved scans restart within their bounded scope after interruption; they
do not resume midway from a directory cursor. Scope and root are checked while
scanning and again at promotion. Existing dispatch ownership, current-version
checks and uncertain-effect review remain the execution safeguards; discovery
itself does not reserve files against concurrent editors.

Bonsai completed three exact planner-provenance edits in session
`logis-discovery-lineage-73ea676`, with terminal completion at event 48. Independent
verification matched all three edits and found the other 203 staged manifest files
unchanged. Cloud work connected discovery, routes and UI and supplied focused
checks. The new two-file discovery/restart path uses synthetic providers; the
previous real local end-to-end evidence above remains separate. No claim of a
new autonomous real-model repository-wide run or live deployment is made.

### New-file authoring through the approved writer

The inventory review identified existing-file-only local coding as the largest
immediately implementable gap: adding a module required a separate manual file
creation. `local_author.py` now records a durable text-only new-file proposal using
the already connected local planner callback. The original Tasks panel accepts a
goal, one explicit new project-relative path and up to two existing context files
(total 12 KB). The target parent must already exist. Generated JSON must name only
the requested path and nonempty UTF-8 content of at most 16 KB. Invalid output,
changed context or uncertain inference stays reviewable without source writes.

After content review, **Save new file for review** creates the existing Foundation
writer and dependent verification job atomically, with a stable proposal-derived
key. This does not approve either job or invoke DSH write tools. The writer appears
in **Background work**, where the user explicitly approves it. Foundation's pinned
Windows create operation and recovery journal refuse to replace a file that
appears before execution. Current scope/root checks, artifact dependencies and
recovery review are reused. Replaying proposal acceptance after the file exists
returns the original tasks; it does not generate or create again. The workflow
inspection action reads those saved tasks without requiring model inference.

This requires both local planning and Foundation to be connected to the same
approved root. Nothing auto-starts them or provisions a directory, identity, grant,
credential or service. Creation is deterministic application file I/O after model
proposal and user approval; it is not a DSH model write. Generated code is not
executed or semantically validated by this feature. Syntax/test execution remains
a separate trusted review task. New-file authoring is one file per proposal, not
an atomic mixed create/edit project plan; Foundation and local-edit ledgers remain
separate. Referencing Foundation artifact IDs as local-edit dependencies is not
supported. Semantic duplicate goals with fresh keys are not universally detected.

Bonsai session `logis-author-hooks-0e55b03` completed the bounded public metadata
hook with read/edit/read, terminal event 33. Exact verification matched the one
requested edit and found all other 206 staged files unchanged. Cloud implementation
supplied the authoring workflow, API/UI integration and tests. `new-file-test-results.json`
records 26 passing synthetic provider checks, including approved creation and verification
after runtime reconstruction, replay suppression, collision no-loss, stale context,
invalid output, revoked scope, API boundaries and activation regressions. The
original UI DOM fixture also checks retained request keys and separate review.
No new real-model authoring quality benchmark or live activation was performed.

### Mixed create/edit plans and bounded syntax checks

The original Tasks panel now combines completed new-file and existing-file
proposals into one mixed plan in the chosen order. Admission is atomic in the
private Foundation ledger: plan identity, source-proposal claims, all write jobs,
verification reads and dependencies commit together or all roll back. Each writer
still requires separate approval in Background work. Each later writer waits for
the preceding writer's committed artifact, whose current hash is rechecked before
execution. Per-file recovery journals remain in effect. This is not an atomic
multi-file filesystem transaction: earlier approved files can complete before a
later step fails, is canceled or needs review. Each verification read waits for its
own writer; later writers do not require that read task to finish first.

Mixed plans use deterministic approved Foundation writes for both creation and
editing. Existing edits are converted from the saved source snapshot and exact
replacement into full reviewed content plus the original expected hash. This
avoids another inference round merely to apply already generated content. Original
standalone DSH edit execution remains available. Source proposals already assigned
to a mixed plan cannot subsequently be accepted through the standalone buttons.
Separate acceptance that already exists is rejected when assembling a mixed plan.
The authenticated acceptance routes share a nonblocking PostgreSQL project
advisory lock across app processes, preventing simultaneous standalone and mixed
acceptance from bypassing those checks. Busy requests retain their identity for
retry. Trusted direct Python callers must provide equivalent serialization; there
is no distributed transaction or undo of effects across the two SQLite ledgers.
Dispatch-time hash/ownership checks still prevent blind replay and overwrite.

Bounds are eight distinct files and 64 KB total proposed content. New-file paths
must be absent in existing directories; existing files must match their proposal
versions. Stable plan keys replay the original saved plan, including after effects.
Changing title, proposal versions, principal or manual-review acknowledgement under
the same key is a conflict. Saved plan inspection returns at most 20 recent plans
and explicitly marks more; it needs no model call. Root/principal metadata is
excluded from the public response. Proposal content remains available for review.

`source_validation.py` uses a fixed trusted Python subprocess, `-I -S`, a minimal
environment, stdin source data, no shell and a three-second deadline per file.
Python is compiled without execution; JSON is parsed with non-JSON numeric
constants rejected. Nothing imports the proposed module or executes its tests or
commands. Result evidence includes the exact proposed source SHA-256 and explicitly
states syntax-only validation and no semantic tests. Unsupported languages require
an explicit manual-review acknowledgement in mixed plans; invalid syntax or an
unavailable parser blocks admission regardless of that acknowledgement. The
parser process is bounded but is not an OS security sandbox for executing code.
JavaScript/TypeScript and project test suites still need trusted validation adapters.

Bonsai session `logis-mixed-transaction-c03b481` supplied two exact edits to compose
`submit_verified_write` inside a caller-owned transaction. Completion event 48 and
independent byte verification confirmed those changes and all other 209 staged
files unchanged. It made extra readbacks beyond the requested four-call budget;
this is supervised implementation, not proof of strict prompt-budget enforcement.
Cloud work supplied mixed-plan admission, UI/API composition and the syntax checker.
The focused integration report is `mixed-plan-test-results.json` (35 passing tests).
The later admission-lock API regression is in `mixed-admission-test-results.json`.
Final checker refinements and unsupported-language gates are recorded separately
in `mixed-validation-test-results.json`; the earlier suite is not relabeled as a
rerun. The UI DOM fixture passed selection, removal, retained keys, acknowledgement,
status inspection and separate approvals. No live application was activated.

### JavaScript/TypeScript and saved project verification

The existing bundled Node v24.22.1 supplies the JavaScript/TypeScript syntax path;
no packages were downloaded, installed or changed. `javascript_validation.py`
selects the fixed Node binary beside the trusted Python runtime dependencies,
not a project executable or PATH lookup. A fixed Node script receives bounded
source through stdin in a three-second subprocess with a minimal environment
(no NODE_OPTIONS/NODE_PATH), no shell, and no project working directory. JavaScript
is compiled with built-in VM APIs without linking or evaluation. TypeScript uses
Node's built-in type transformation, followed by the same compilation check.
Neither source imports, package scripts, plugins nor tsconfig files are loaded.

`.js`, `.mjs`, `.ts` and `.mts` are checked as modules; `.cjs` and `.cts` use
CommonJS function-body parsing. `.js` does not infer package.json module mode.
JSX/TSX remains unsupported. This does not perform TypeScript type checking,
module/dependency resolution or semantic tests. Node-specific unsupported syntax
fails or reports unsupported rather than silently receiving a success result.
Missing/incompatible trusted runtimes and timeouts fail closed. The trusted runtime
location is environment-specific and must be provided by deployment; no runtime
installation occurs. Mixed-plan admission automatically uses these syntax results.

The original Tasks panel additionally supports **Start current-file verification**.
It saves a durable `local_verify` job for one to eight explicit project files,
at most 64 KB combined, independent of model availability. Selected hashes are
captured at admission, compared before/after each check and rechecked across the
selection afterward. Changed or missing versions cannot produce a completed
report. Reports contain per-file status/hash and aggregate `passed`; unsupported
languages and syntax failures produce `passed: false`, even though the reporting
job itself completed successfully. Scope/root revocation and cancellation are
respected; a running parser can take up to its three-second deadline to return.

Verification source is never executed and the job creates no file artifacts.
The snapshot/report survives runtime reconstruction. Replaying the same key returns
the saved report; after successful submission another explicit UI click requests
a fresh snapshot. An uncertain reply keeps its key. This is selected-file syntax
verification, not an atomic repository snapshot, a dependency graph check, mixed
plan completion certification or proof of functional correctness. File versions
can change after checking. Arbitrary test commands and generated tests are still
not executed automatically; a trusted semantic-test environment remains work.

Bonsai session `logis-verification-hook-43a118a` supplied the exact public metadata
hook. Independent comparison verified the edit and all other 215 staged files
unchanged. Cloud work supplied parser/job/API/UI integration and focused tests.
`project-verification-test-results.json` records 27 passing tests. Real bundled
Node/Python processes parsed valid/invalid sources, including TypeScript enums,
module imports without resolution and code that would write a sentinel if run.
No sentinel was created. A deliberate type mismatch passed syntax checking,
explicitly documenting the absence of type checking. Other cases cover restart,
replay, fresh checks, stale/concurrent files, bounds, missing runtime, timeout,
cancellation, current scope, public metadata and mixed-plan regressions. The DOM
fixture passed key preservation and fresh-check behavior. No live activation or
model/GPU/security/service changes occurred.
