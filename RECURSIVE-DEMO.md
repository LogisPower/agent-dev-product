# Real local recursive analysis demonstration

On 2026-10-31, the staged adapter completed a synthetic read-only analysis using
the existing resident model and existing shared inference lock. No service, model,
GPU, credential or permission setting changed. This was not a benchmark.

- Input: one 17,980-byte synthetic requirements file, above the single-leaf limit.
- Tree: source spans `0:8990`, `8990:17980`, then synthesis `0:17980`.
- Result: all three nodes durably completed; task status `completed`.
- Provider calls: 23.36 seconds, 24.20 seconds and 4.78 seconds, about 52.34 seconds
  total. Each retained the configured 90-second bound; no retries occurred.
- Output: “Completed tasks must retain exact artifact evidence, and changed source
  must be reviewed before edits.”
- File evidence: source SHA-256 remained
  `3613a19aca04761de95b8f9135110b45e7123837bc07219ef899354d6b20f052`.
  The synthetic project still contained only `requirements.txt`; no edit provider
  was called. Node results and checkpoints were saved in separate temporary state.
- The endpoint advertised `bonsai-27b-uncensored`. An alias is not proof of actual
  weight size or GPU placement; the demonstration did not change or identify those.

The prompt deliberately requested an empty quote list. This demonstrates actual
recursive inference, saved results and no source writes, not real-model quote-span
accuracy or semantic grounding. Quote rejection, cancellation, restart and stale
source behavior have focused synthetic tests; this run did not interrupt inference.
Summary text remains explicitly unverified navigation context.

The UI now distinguishes ordinary retry (same request identity) from **Start a fresh
analysis** (an explicit new request and call budget). The expanded DOM fixture checks
that ordinary retries preserve the key and fresh analysis changes it while retaining
the draft. The running UI has not been replaced with this staged implementation.
