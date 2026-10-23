# Logis

Source baseline for the local Windows AI workspace and phased backend rework.

Not a complete installer. Machine-specific paths marked LOGIS_USER require configuration. Models, dependencies, databases, browser runtimes and private state are excluded. The running installation is separate from this development copy.

## Improvement pipeline
Issue or capability gap -> feature branch -> tests -> draft PR -> review -> explicit release. No automatic merging or deployment.

## Recursive context
rework/recursive_context.py is a bounded divide-and-summarize experiment, not the full research RLM environment or model retraining. Production model wiring, cancellation and source-grounding evaluation remain outstanding.

## Checks
python rework/test_records.py

python rework/test_recursive_context.py

node --check app.js

node --check workspace.js
