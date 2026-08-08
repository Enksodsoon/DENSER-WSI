# Autonomous Execution

The phase runner resumes from atomic, hashed checkpoints and continues after
scientific threshold misses. It stops only after a valid completion marker or a
fail-closed terminal integrity/data-governance incident.

The final holdout has one automatic gate: create and verify the immutable freeze
record, commit its private local record outside public Git, then run the final
holdout once. No human unlock is required. Post-freeze changes create a separate
exploratory run and cannot replace the primary result.

Execution status and scientific outcome are independent fields. Resource or
external-access limits never become scientific negatives.
