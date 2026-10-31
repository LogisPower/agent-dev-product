# Opt-in activation adapter (not activated)

`rework/activation_adapter.py` constructs the original Logis UI, durable file
runtime and existing canonical API. It is a Python factory, not a launcher or
installer. Importing it creates no files, projects, grants, processes or listeners.
The proposed `logis-development` identity and Docker mapping were exercised only
against temporary synthetic files and a disposable PostgreSQL cluster.

## Explicit inputs and sequence

1. Separately approve and provision an intended canonical project, its exact
   filesystem root, separate private runtime state directory, and the intended
   existing identity's project scope. Nothing in the adapter performs these steps.
2. Construct `Binding(project, root, container_root, state_directory)` using the
   exact existing mapping. `binding.expected_approval()` describes the required
   approval record but does not install or authorize it. A trusted server-side
   read-only loader must supply the separately approved record on every check.
   Keep this record and credentials outside the model-writable project tree.
3. Call `create_activation_app(binding, dsn, credentials, approval_reader, ...)`.
   The existing canonical DB must pass the candidate's isolated-restore-path
   guard. Missing or archived projects, absent scope, altered approval, linked
   paths, missing folders and conflicting private state fail closed. Arbitrary
   production databases are deliberately refused; the path guard alone is not
   an authorization mechanism.
4. After these checks, the factory initializes `binding-state.json` and
   `tasks.sqlite` in the private directory. The marker prevents accidental
   rebinding; it is not a grant. Existing unmarked ledgers require an explicit
   migration instead of silent adoption. Workers remain off by default.
5. Optional `start_workers=True` requires explicit existing chat and build
   adapters and starts Foundation and durable chat/build workers on app lifespan.
   It does not start global outbox/understanding workers or load a model. The
   caller must separately coordinate provider settings, active work, listener,
   service cutover and rollback. No activation entrypoint has been installed.

## Security and effect boundaries

- Scope is intersected with the one selected project; existing write/read limits
  remain. Revoked approvals, current credential/device scope and archived project
  state are rechecked. File effects take the canonical project lock so archive
  and effect completion serialize. This does not revoke the Windows account's
  existing OS permissions or shrink the existing DSH Docker bind.
- Both durable file jobs and shared chat workspace tools use the same exact root
  and Docker mapping, with bounded reads, version checks, pinned handles and
  recoverable writes. They cannot fall back to the legacy Documents workspace.
  Setup/checklist tools retain their separate existing authorization path.
- Durable writes require their existing explicit task approval. Shared chat writes
  retain their existing intent/credential gates and active-run checks; they do
  **not** gain the Foundation approval UI as an additional gate. Granting write
  scope therefore authorizes that existing chat tool path too. No shell execution
  is introduced by this adapter.
- Approved durable writes can provision the reserved `.logis` journal within
  the selected root; shared mutations require that journal already exist. Preserve
  journal receipts and private SQLite state on recovery and rollback. Model file
  tools exclude hidden control paths. Keep all credentials and approval records
  outside the selected root, including non-hidden files.
- Exact mapping is supplied and trusted by the server, not verified by contacting
  Docker. The previously inventoried bind must be rechecked at deployment.
  Trusted administrators must protect the loader and private state directories;
  this factory is not an OS sandbox against the same Windows principal.

## Remaining approval and deployment work

The proposal is `logis-development` / **Logis Development**, rooted solely at
`C:\AI\Projects\logis-harness-next\original-logis`, mapped to
`/workspace/logis-harness-next/original-logis`, with private state at
`C:\Users\LOGIS_USER\AppData\Local\LogisRework\foundation\logis-development`.
It is not a live project, grant or service configuration. The user's C:\AI choice
and authorization to test this proposal do not authorize live activation.

Approval is still needed for that exact binding, canonical project creation,
identity scope change, protected approval-record/private-state provisioning,
and separately coordinated service activation. A concrete deployment entrypoint
and trusted approval loader must be prepared and reviewed before cutover. No
credentials, permissions, model selection, GPU settings or live services changed.

## Evidence

Local Bonsai session `logis-activation-hooks-5b3f422` made the bounded edits to
`candidate_api.py`, `shared_tools.py`, `workspace_facade.py`, and `tool_catalog.py`.
Exact replacement and hash verification confirmed all other 171 staged files
unchanged. Cloud authored the factory and tests and checked the integration.
The consolidated suite passed 65 tests; focused activation validation after the
worker-start restriction is recorded in `activation-test-results.json`.
This demonstrates synthetic integration, not a live deployment or autonomous
local ownership of the whole application.

## Optional local-task UI integration

The factory can additionally receive an already authenticated `local_transport`
whose project and container cwd exactly match the approved binding. It creates a
separate `local-work.sqlite` in private state and registers scoped local-task
routes for the original Tasks panel. This adds no credentials or permissions.
The local worker stays stopped even with `start_workers=True`; a separately
coordinated owner must explicitly start/stop it. See `LOCAL-WORK.md` for exact
approval, current-scope, dependency, conflict and recovery behavior and limits.

The optional `local_planner` callback enables text-only goal-to-plan proposals
without tool execution. It must preserve current local provider identity, shared
slot admission, bounded output/deadline and cancellation behavior. Supplying it
creates no grants or auto-started workers. Proposal acceptance and each edit's
approval remain separate user actions. See the goal-driven proposal section of
`LOCAL-WORK.md` for the tested bounds and actual synthetic-file model evidence.

## Prepared trusted entrypoint (still not activated)

`rework/activation_entrypoint.py` now supplies the missing launch composition.
`check_configuration(absolute_config_path, adapters)` is read-only: it checks the
explicit binding, separately provisioned approval, existing scoped credentials,
isolated DB project, required directories, private-state ownership marker and
adapter requirements. It does not create private state, credentials, grants,
projects, workers or a listener. A successful check is not activation approval,
port reservation or provider-readiness evidence. The CLI exposes only this check:

```text
python rework/activation_entrypoint.py --check <absolute-existing-config.json>
```

The config has exactly six fields:

- `binding`: `project`, absolute `root`, `container_root`, absolute `state_directory`.
- `database_file`: absolute path to an existing private JSON object containing only `dsn`.
- `credentials_file`: absolute path to an existing credential map, each token mapped to exactly `projects` (list) and `write` (boolean).
- `approval_file`: absolute path to the separately approved exact `Binding.expected_approval()` record.
- `listener`: exactly `host: "127.0.0.1"` and an explicitly chosen integer `port` from 1024 to 65535.
- `workers`: explicit booleans `foundation`, `chat`, `local`. Existing chat startup requires Foundation too.

All four config/control files must be distinct, absolute, already present and
outside the model-writable project root. Reads reuse the Windows pinned-handle
adapter, rejecting reparse paths and hard-linked files. JSON is bounded and duplicate
fields are rejected. Credentials and approval are reread during existing request/
dispatch checks so revocation is effective. The database target and worker selections
are startup settings, not hot-reloaded configuration. No ACL changes or protection
against the same unrestricted Windows account are claimed; operators must protect
these files. CLI failures expose an error type without DSNs, tokens or tracebacks.
This first loader supports existing bearer credential maps; it does not migrate
preview-token files or provision/reuse a device-session store automatically.

A separately authorized trusted host constructs `RuntimeAdapters` from existing
chat/build callbacks, context counter, authenticated bound DSH transport and
text-only local planner callback as appropriate, then calls:

```python
from activation_entrypoint import RuntimeAdapters, serve
# Supply verified, already authorized callbacks from the owning runtime.
adapters = RuntimeAdapters(
    request_chat=existing_chat,
    request_build=existing_build,
    local_transport=existing_bound_transport,
    local_planner=existing_text_planner,
)
serve(approved_config_path, adapters)
```

These symbols are intentionally not guessed or dynamically imported from JSON.
Provider adapters retain responsibility for verified identity, shared model-slot
coordination, bounded requests and cancellation. A CLI check with local/chat workers
selected fails without required injected adapters; a trusted host can call the
Python checker with them. `build_application` initializes only the already approved
private ledger state and constructs the original UI without starting a listener.
`serve` is the explicit listener-starting function and is not invoked by the CLI.
It uses one Uvicorn process, loopback only, no auto-reload or access logs. Nothing
calls the legacy model-loading launcher.

On app lifespan entry, only selected workers start. Global outbox/understanding
workers remain excluded. Startup failure and shutdown request cleanup of owned
workers, using existing bounded shutdown/cancellation behavior; this is not a
claim of instantaneous resident-model compute cessation. Local worker status stays
available through the existing Tasks panel. Bonsai supplied the bounded candidate
app shutdown hook in session `logis-runtime-close-f57e0a0`, completed event 38.
Exact comparison verified that edit and 219 other staged files unchanged.

`entrypoint-test-results.json` records 27 passing disposable integration tests.
The final durable-chat routing/lifespan refinements are checked separately in
`entrypoint-lifecycle-test-results.json`. Fixtures proved read-only checking creates
no private state, original UI availability, existing credential/approval revocation,
no source effect before approval, one approved synthetic local edit, owned-worker
shutdown, failed-startup cleanup, control-file rejection and redacted CLI errors.
The listener call was mocked; no new live listener or service was activated. These
are synthetic execution/lifecycle checks, not a live Bonsai cutover.

### Specific remaining activation inputs

The proposed project/root/private-state pairing above is still unapproved for live
activation. No canonical project, scope, control files or service was provisioned.
A trusted host must supply the existing provider adapters and choose the explicit
loopback port. The original device-session authentication choice also remains to
be integrated if bearer-map authentication is not the desired deployment mode.
After those inputs and per-action approvals, deployment still requires checking
active work, confirming the Docker mapping, coordinating cutover and preserving
rollback state. Full semantic project testing and broad autonomous coding remain
separate capability limits; this entrypoint does not claim to solve them.

## Existing provider adapters and exact read-only inventory

`local_provider_adapters.make_existing_adapters(binding, shared_lock, rpc)` now
constructs chat, build, text-planner and coordinated DSH callbacks for the trusted
entrypoint. It preserves the existing `local_model_config` and streaming transport;
construction does not probe, generate, authenticate or load a model. Callers supply
the existing absolute shared lock outside the project. The lock is opened `r+b`,
never created or initialized; pinned ancestors, identity/link checks and a
nonblocking OS lock prevent silent use of a different/new lock. Chat, build and
planner calls check configured alias/context and resident slot status while holding
that same existing lock, then use the existing cancellation-aware HTTP completion.

The coordinated DSH transport holds the shared lock from admission through an
observed terminal session event or cancellation request. It cancels only the owned
job session. Provider probe/submission failure releases the lease. Callers must
poll or cancel accepted handoffs; the durable local loop does this. Cancellation
and lock release do not prove resident compute stopped; subsequent calls still
check slots. Unrelated DSH clients do not participate in this Windows lock, so a
universal race-free reservation across all clients is not claimed. The current
local loop now waits for provider admission before crossing its submission boundary;
see the bounded admission behavior below. Submitted jobs are never automatically replayed.

Admission waits at most the smaller of the task timeout and 120 seconds, plus an
in-flight bounded metadata probe. It checks cancellation/shutdown, records a
`waiting_for_provider` checkpoint, and retries only acquiring the existing lock
and checking idle status. It makes no DSH submission or remote cancellation while
waiting. A known pre-submission timeout fails without uncertain-effect review.
After admission, scope, root, target versions and dependency hashes are rechecked.
The existing execution timeout starts after submission; no instant reply is promised.
See ACTIVATION-CHOICE.md for the concise decision and exact security implications.

`existing_dsh_rpc.ExistingDshRPC(port, cookie_reader)` is a bounded loopback RPC
client for an already authenticated session. It rereads the supplied cookie on
every request, permits only session create/prompt/projection/page/cancel/list,
rejects redirects and malformed headers, bounds request/response bytes, and uses
socket timeouts plus a 15-second socket shutdown timer. It never reads launch logs,
logs in, extracts browser cookies, writes a cookie file, creates credentials or
changes DSH settings. The trusted host must supply an authorized existing cookie
reader (or an existing authenticated RPC callback instead). Values stay in memory.

Example composition, after separate authorization and provisioning:

```python
from existing_dsh_rpc import ExistingDshRPC
from local_provider_adapters import make_existing_adapters
from activation_entrypoint import load_configuration, serve
_, binding, _, _, _ = load_configuration(approved_config_path)
rpc = ExistingDshRPC(3080, existing_authorized_cookie_reader)
adapters = make_existing_adapters(binding, existing_shared_lock_path, rpc)
serve(approved_config_path, adapters)
```

The read-only inventory on 2026-10-31 confirmed:

| Item | Observed existing value |
|---|---|
| Logis listener | `127.0.0.1:8092` |
| DSH listener | `127.0.0.1:3080` |
| Model listener | `127.0.0.1:8080` |
| Private Logis origin | `https://logis.example.invalid` (`443` proxies to `8092`) |
| Private DSH route | HTTPS `8443` proxies to `3080` |
| Device cookie | `__Host-logis_device`, tied by existing code to the private Logis origin |
| Existing Logis token file | `C:\Users\LOGIS_USER\Documents\Codex\2026-10-22\us\outputs\Local AI\Builder\rework\preview-access.json` present |
| Existing device store | `C:\Users\LOGIS_USER\AppData\Local\LogisRework\auth\device-sessions.sqlite` present |
| Shared inference lock | `C:\Users\LOGIS_USER\Documents\Codex\2026-10-22\us\outputs\Local AI\Builder\runtime\inference.lock` present |
| Proposed private runtime directory | `C:\Users\LOGIS_USER\AppData\Local\LogisRework\foundation\logis-development` absent |
| Proposed side-by-side port | `127.0.0.1:8094` was not listening; not reserved or activated |
| Model-advertised alias | `bonsai-27b-uncensored`; alias alone does not prove actual weight size |

No token/cookie values or device secrets were printed or copied during inventory.
No proxy, listener, authentication, lock content, model or GPU configuration changed.

The actionable activation plan is:

1. Approve the proposed `logis-development` identity, its exact staged source root
   and container mapping, and separate private runtime directory already described.
   No parent `C:\AI` or `/workspace` grant is proposed. Binding operations remain
   read/create/edit/move; no delete grant is added.
2. Identify the existing owner/device scope to reuse, then approve only the needed
   project-scope/control-file provisioning. The new entrypoint currently consumes
   an existing bearer map; do not assume that an existing preview-token JSON is
   already in that format. Existing device-login reuse needs explicit integration
   and the same HTTPS origin, not merely a new loopback port.
3. Choose either the proposed side-by-side `127.0.0.1:8094` listener (leaving current
   `8092` and HTTPS routing intact), or a separately coordinated `8092` cutover that
   preserves the current origin/authentication. No port is chosen implicitly and
   no proxy modification is included in a side-by-side launch.
4. Supply the existing authenticated DSH cookie reader/RPC callback and existing
   shared lock to the prepared adapter factory. Do not mint replacement credentials
   or create a second lock. Retain the currently configured model; alias/slot
   verification must pass before any generation. No model switch is proposed.
5. Provision the separately approved private config, DB descriptor, narrowed
   credential map and exact approval record outside project files; run the read-only
   checker with adapters. Before an authorized launch, recheck active jobs, port
   availability and the Docker mapping, preserve both ledgers/journals, and arrange
   rollback without deleting uncertain state. Only then invoke the reviewed serve
   entrypoint with the selected worker flags.

Bonsai session `logis-provider-guard-02266fd` completed two bounded RPC receipt
validation edits at event 43. Independent comparison verified both edits and all
other 223 staged files unchanged. `provider-adapter-test-results.json` records 29
passing focused checks using temporary locks, synthetic callbacks and a real
loopback RPC fixture, alongside existing lifecycle/recovery tests. Live model
identity inspection was read-only; the new adapters were not used for live
inference or service activation. Semantic project testing, full autonomous coding
and existing device-auth deployment integration remain limitations.
