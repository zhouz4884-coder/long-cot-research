# Phase5 quality: CPU_INTERFACE_ONLY_COMPLETE

Complete four-method cases: 3; basis complete: 6.

One-shot prompt prototypes, no runtime derived-value checker. Guard/EOS and parser score are separate.

| Method | N | Numeric correct | EOS and correct | Hit cap | Unparsed |
|---|---:|---:|---:|---:|---:|
| SharedGDirect | 3 | 0 | 0 | 3 | 3 |
| SharedGCompact | 3 | 0 | 0 | 3 | 3 |
| SharedGStepwise | 3 | 0 | 0 | 3 | 3 |
| VersionFrame | 3 | 0 | 0 | 3 | 3 |

## Scope

- Two arithmetic programs with E/C/W variants: exploratory development fixtures, not six independent natural tasks.
- G certifies constant roots parsed from visible original definitions; old y/z stay UNVERIFIED.
- All four methods share G/rules/graph/old records/R; no group or gold chooses a method or bypass.
- VersionFrame is one-shot prompted organization, not runtime node checking or certified final submission.
- No training, cache mask/crop, steering, teacher-forced scoring, auxiliary probes or forced tail window.
- Real free outputs continue to configured EOS or the 512-token safety guard; the random CPU fixture has an explicit shorter guard. No parser-based early stopping.
- Safety-cap/unknown/unparsed/failures remain visible; incomplete four-arm cases are not silently completed or replaced.
- Per-method quality/cost is not compared with the prior P0.5 run's different prompts/protocol.
- Shared input preparation and model loading are experimental overhead; actual per-request G/prompt/prefill/decode costs are separate.
- Numeric final-answer extraction is posthoc grading, not a runtime model/tool correctness gate.

Random tiny CPU fixture/chunk tokenizer only; no trained-model quality evidence.
