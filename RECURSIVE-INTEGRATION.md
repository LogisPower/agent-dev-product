# Existing recursive setup: verified wiring and next integration

**Staged update:** the recovered reducer is now present and connected through
`local_analysis.py`, the scoped planning API and original Tasks UI. The inspection
below describes the earlier local state; it is retained as historical evidence.
The bounded implementation and remaining limits are documented in LOCAL-WORK.md.
It has not been activated in the running service.

Read-only inspection, 2026-10-31. No generation, cloning, GitHub writes, service
activation or security changes were required for this check.

## What exists

GitHub repository: https://github.com/LogisPower/agent-dev-product

The main branch contains `rework/recursive_context.py` and its test, plus
`.github/workflows/checks.yml`. The reducer divides text into chunks and combines
model-generated findings. Defaults are 96,000 source characters, 6,000-character
chunks, 24 calls and depth 6. It does not edit files, schedule durable work, open PRs,
or retrain a model. Its source spans record provenance but do not prove that a
generated finding is grounded. The README marks production wiring/cancellation/
grounding evaluation outstanding. GitHub Actions runs checks on push and PR, with
read-only contents permission. The improvement pipeline is a documented review
process, not a running autonomous GitHub agent. Draft PR #2 is still open.

## What is installed and connected

| Location/path | Verified finding |
|---|---|
| Development `Logis/rework` | Neither `recursive_context.py` nor `test_recursive_context.py` exists. No recursive reducer import/caller found in Python source. |
| `C:\AI\Projects\logis-harness-next\original-logis` | Same absence; `.github/workflows/checks.yml` also absent. `AGENTS.md` carries the branch/draft-PR/review rules. |
| `C:\Users\LOGIS_USER\Documents\Codex\2026-10-22\us\outputs\Local AI\Builder` | Reducer, its test and GitHub workflow absent from the corresponding paths. Root and rework Python scans found no reducer imports/calls. |
| Current `127.0.0.1:8092` process | Python command references the known live Builder path and `serve_candidate.py`. Only script identity was extracted; no command-line secrets recorded. |
| Live `rework/serve_candidate.py` | Creates the candidate API with background chat and registers the existing bounded-chat provider; serves 8092. |
| Live `rework/candidate_chat.py` | Uses `harness_queue.scheduler`, existing completion transport, bounded tool passes and optional answer synthesis; no recursive reducer import. |
| Older live `server.py:511` | Calls `graph_runner.run`; that graph has a recursion limit. This older entrypoint is not the identified 8092 process. A graph recursion limit is not the GitHub context reducer. |
| Staged `rework/activation_adapter.py` | Constructs `LocalPlanner` only when the caller supplies both local transport and planner callbacks. The staged activation entrypoint has not been launched. |

This is source/process-path evidence. It does not inspect Python heap state or
claim a request was executed during inspection. No evidence of live execution of
the GitHub recursive reducer was found. Port 8094 was not listening at inspection.

## Comparison with the staged planner

The staged planner accepts a goal and one or two current files totaling at most
12 KB. It makes one text-only planning request, validates exact replacement anchors,
and retains reviewed proposals in the durable ledger. Execution needs separate
approval. It checks current versions and includes completed/uncertain-work evidence.
Discovery searches bounded project files without model calls. The local executor
performs exact edits with durable receipts, cancellation and uncertain-outcome review.

The GitHub reducer could help understand larger sources; it cannot replace these
write/recovery protections. Adding it to every current small planning request would
spend extra model calls without solving an observed gap. It was not silently copied
or enabled as part of this inspection.

## Practical integration path

1. Keep current small-file planning unchanged. Add an explicit read-only larger-source
   analysis task only when needed. Review the existing GitHub reducer as the starting
   algorithm; do not treat its raw callback as a production provider adapter.
2. Read through the existing scoped file interface. Save source hashes and spans in
   a durable analysis task, reject changed files, and store each completed chunk
   result so cancellation/restart does not redo completed calls. Bound bytes, total
   calls, depth, output and overall elapsed time; start with a small serial call budget
   on the single model slot. Check cancellation and authority between calls and use
   the existing cancel-aware provider. Uncertain inference must remain reviewable.
3. Treat summaries as untrusted navigation hints. Re-read selected source spans and
   their current hashes before creating exact edits; never fabricate anchors from
   summaries. Feed the narrowed source to the existing planner and approval flow.
4. Keep GitHub review separate from local execution. After an explicitly authorized
   future connection, package reviewed source-only changes on a feature branch for
   a draft PR and existing CI. Preserve secret/private-state exclusions and explicit
   release approval. No automatic merge or deployment and no new GitHub write scope
   are implied by discovering the repository.

Focused acceptance cases for that future implementation: cancellation between and
within model calls, exhausted call/time budget, restart after a completed chunk,
changed source, ungrounded summary, invalid anchors, duplicate task key and withdrawn
scope. This integration is specified, not implemented or claimed tested here.

## Activation remains a separate decision

See ACTIVATION-CHOICE.md. Recommended initial choice is side-by-side loopback 8094
with the exact `logis-development` root and existing identity/auth inputs approved.
Current 8092 stays available, though both share model capacity. Replacing 8092 needs
coordinated cutover and verified existing-device authentication integration. Neither
choice automatically connects GitHub or enables recursive analysis.
