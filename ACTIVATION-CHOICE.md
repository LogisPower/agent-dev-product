# Activation decision — not applied

## Exact proposed scope

Project identity: `logis-development` (Logis Development).
Windows root: `C:\AI\Projects\logis-harness-next\original-logis`.
Container root: `/workspace/logis-harness-next/original-logis`.
Private runtime state: `C:\Users\LOGIS_USER\AppData\Local\LogisRework\foundation\logis-development`.
Proposed file capabilities: read, create, edit and move within this root; no delete
or parent-directory grant. Existing chat write intent/credential gates still apply;
the separate durable-task approval gate is not a gate on every legacy chat write.
The existing DSH container has a broader `/workspace` mount: task scoping is not
an OS sandbox or a new restriction on existing DSH clients.

| Choice | User/work impact | Approval and remaining work | Reversal |
|---|---|---|---|
| Side-by-side `127.0.0.1:8094` — recommended first | Leaves current 8092 and private HTTPS route intact. Shares model capacity and the selected canonical DB; it is not data isolation. | Approve project scope, protected control/state provisioning, existing identity/auth reuse and this listener. Supply an authorized existing DSH RPC/cookie reader. Current entrypoint uses a scoped bearer map; existing secure device cookie login is not automatically inherited at this HTTP port. | Stop the new service. Preserve ledgers and journals. File/database writes remain; stopping does not undo them. |
| Replace `127.0.0.1:8092` | Existing users see the new app through the current HTTPS route; coordinated downtime and an active-job drain are required. | Same scope approvals plus service cutover. Existing device login must be integrated and verified before replacement. Back up and preserve current app/state. No proxy change is needed if 8092 and the origin stay the same. | Restore the old app/listener with preserved state. Data compatibility must be checked; uncertain jobs cannot be blindly replayed. |

No credential creation, device-store migration, proxy/firewall change, model switch,
GPU change or activation has been performed. Exact existing owner/device identity,
credential-map format, DB target and authorized DSH cookie source remain inputs to
resolve privately before launch. Existing token-file presence alone does not prove
format compatibility or authorize broadening its scope. The read-only configuration
checker must pass after authorized provisioning, and port/job/mapping checks must
be refreshed immediately before launch. See ACTIVATION.md for observed paths.

Ready decision: approve side-by-side 8094 with the exact project scope above, or
choose a coordinated 8092 replacement after device-auth integration. This document
does not grant either option or imply the unfinished authentication integration is ready.

## Recovered GitHub setup (read-only, 2026-10-31)

Verified repository: https://github.com/LogisPower/agent-dev-product

- `README.md` defines issue/gap -> feature branch -> tests -> draft PR -> review ->
  explicit release, with no automatic merge/deploy.
- `rework/recursive_context.py` contains the bounded divide-and-summarize prototype
  (96,000 input characters, 24 model calls, depth 6 by default). The README explicitly
  says production model wiring, cancellation and grounding evaluation are outstanding.
- `.github/workflows/checks.yml` runs syntax and records/recursive-context tests on
  push/pull_request with read-only contents permission; it does not run an autonomous
  improvement agent.
- Draft PR #2, `feature/canonical-writes`, remains open for the canonical backend.
- The inspected local development checkout and live Builder did not report a Git
  remote URL. This verifies the GitHub development/review setup, not a currently
  running recursive coding loop or a connection from the new staged checkout.

No repository clone, push, workflow trigger or GitHub configuration change occurred.
