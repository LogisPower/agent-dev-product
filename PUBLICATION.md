# Source reconciliation

This branch starts from the existing `feature/canonical-writes` head
`efd68972336fa8bbe605619cd6268d1f3f4acc6e` and incorporates staged implementation
checkpoint `ecfd52a621f9d2e40b0219c688d4cc9ee602478c` as a source-only export.
The existing draft PR and main are unchanged. Remote-only source, tests, recursive
experiment and workflow are retained; no files are deleted.

Implementation and tests are included, not just descriptions. Machine user names
and private origins use documented placeholders. The export is configuration-distinct
from the installed checkout; copying it over a live installation requires review.

Excluded: local test-result JSON, screenshots, installation inventory, private
machine planning notes, databases, credentials, logs, dependencies and backups.
No model weights or generated session data are included. Sanitized historical
activation evidence is not a new public endpoint or permission grant.

Local Bonsai supplied bounded edits already included in the staged implementation.
Publication uses deterministic file comparison and review; no extra generation
was needed to copy or sanitize source.

Rollback: close the draft PR and leave the branch unmerged. Publication does not
activate services or migrate data. Existing live files remain untouched.

Export validation: 33 focused Windows provider/admission/cancellation/lifecycle/
local-work tests passed on the sanitized source using disposable PostgreSQL and
synthetic providers. Four original-UI DOM fixtures passed. All exported Python
files parsed successfully. This is focused validation, not a full-suite or browser
visual acceptance claim. Hosted CI results must be checked separately.

Pre-publication inspection covered all 221 text files (about 1.34 MB, largest
about 65 KB), including retained files. No binary/oversized artifact, known token
format, private key, personal username or private machine origin was detected.
The one literal-secret scan match is a synthetic test fixture. Pattern scanning
is a check, not a guarantee of exhaustive secret detection.
