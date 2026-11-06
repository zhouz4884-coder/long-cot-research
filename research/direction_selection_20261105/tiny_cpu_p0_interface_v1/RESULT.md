# P0 result: CPU_INTERFACE_ONLY_COMPLETE

Completed 3 injected states; elapsed 5.89s.

The five arms preserve all KV tensor slots. No memory-saving claim is supported.

| Arm | Completed | Strictly correct |
|---|---:|---:|
| full | 3 | 0 |
| target_late | 3 | 0 |
| target_early_reprefill | 3 | 0 |
| random_late | 3 | 0 |
| random_early_reprefill | 3 | 0 |

## Limits

- Handwritten teacher-forced injected states; not natural errors, detection or self-correction.
- Revisions are shared visible injections, including wrong revisions; no independent verifier message.
- All cache tensors keep their original shapes; masking establishes no memory saving.
- Target is a whole provided branch; random is a token subset of B union U, with overlap recorded.
- No causal correctness, general accuracy, long-CoT efficiency, novelty or deployment claim.
- Only one fixed seed/mode; no selection of cases or continuations by observed performance.

Random tiny CPU weights and fixture tokenizer: no pretrained Qwen3 performance evidence.
