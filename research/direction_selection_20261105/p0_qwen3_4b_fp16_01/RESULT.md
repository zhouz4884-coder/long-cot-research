# P0 result: P0_COMPLETE

Completed 16 injected states; elapsed 135.58s.

The five arms preserve all KV tensor slots. No memory-saving claim is supported.

| Arm | Completed | Strictly correct |
|---|---:|---:|
| full | 16 | 0 |
| target_late | 16 | 0 |
| target_early_reprefill | 16 | 0 |
| random_late | 16 | 0 |
| random_early_reprefill | 16 | 0 |

## Limits

- Handwritten teacher-forced injected states; not natural errors, detection or self-correction.
- Revisions are shared visible injections, including wrong revisions; no independent verifier message.
- All cache tensors keep their original shapes; masking establishes no memory saving.
- Target is a whole provided branch; random is a token subset of B union U, with overlap recorded.
- Random scattered B-union-U masking matches only count: not age/contiguous span or Random Attention; beating it does not establish semantic specificity.
- No causal correctness, general accuracy, long-CoT efficiency, novelty or deployment claim.
- Only one fixed seed/mode; no selection of cases or continuations by observed performance.
